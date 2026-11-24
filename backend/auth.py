"""Passwords and login throttling."""
import hashlib
import hmac
import os
import urllib.parse
import urllib.request
import time

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


# Simple in-memory throttle: 8 failed logins per phone number per 10 minutes.
_FAILS: dict = {}
WINDOW, MAX_FAILS = 600, 8


def too_many_failures(key: str) -> bool:
    now = time.time()
    fails = [t for t in _FAILS.get(key, []) if now - t < WINDOW]
    _FAILS[key] = fails
    return len(fails) >= MAX_FAILS


def record_failure(key: str) -> None:
    _FAILS.setdefault(key, []).append(time.time())


def clear_failures(key: str) -> None:
    _FAILS.pop(key, None)


def normalize_indian_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("Enter a valid 10-digit Indian mobile number starting with 6, 7, 8 or 9")
    return digits


def otp_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def send_sms(phone: str, message: str) -> bool:
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    if not sid or not token or not from_number:
        return False
    payload = urllib.parse.urlencode({"From": from_number, "To": "+91" + phone, "Body": message}).encode()
    request = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    auth = (sid + ":" + token).encode()
    import base64
    request.add_header("Authorization", "Basic " + base64.b64encode(auth).decode())
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception:
        return False
