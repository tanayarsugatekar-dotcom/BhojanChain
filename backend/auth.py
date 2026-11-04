"""Passwords and login throttling."""
import hashlib
import hmac
import os
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
