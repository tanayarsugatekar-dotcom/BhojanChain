"""BhojanChain API (Starlette + SQLite).

Run:  uvicorn main:app --host 0.0.0.0 --port 8000
The web app in ../frontend is served from the same server at http://localhost:8000/
"""
import os
import random
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import shelf_life as sl
from auth import (
    clear_failures,
    hash_password,
    normalize_indian_phone,
    otp_hash,
    record_failure,
    send_sms,
    too_many_failures,
    verify_password,
)
from db import connect, init_db, parse_ts, phone_key, utcnow
from areas import AREAS, DATA as AREA_DATA, AddressError, resolve_address
from geo import haversine_km
from schemas import (
    AdminLoginRequest,
    DONOR_KINDS,
    ClaimCreate,
    ListingCreate,
    LoginRequest,
    OTPRequest,
    OrgCreate,
)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
KINDS = {"MARKET_VENDOR", "WEDDING_VENUE", "RESTAURANT", "NGO", "INDIVIDUAL"}


# ---------------------------------------------------------------- request helpers
async def read_body(request: Request, model):
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(400, "Request body must be valid JSON")
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        msg = "; ".join(f"{'.'.join(str(p) for p in x['loc'])}: {x['msg']}" for x in e.errors())
        raise HTTPException(422, msg)


def q_float(request: Request, name: str, default=None, lo=None, hi=None, gt=None):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default
    try:
        v = float(raw)
    except ValueError:
        raise HTTPException(422, f"{name} must be a number")
    if (lo is not None and v < lo) or (hi is not None and v > hi) or (gt is not None and v <= gt):
        raise HTTPException(422, f"{name} is out of range")
    return v


def q_bool(request: Request, name: str) -> bool:
    return request.query_params.get(name, "").lower() in ("1", "true", "yes", "on")


def q_choice(request: Request, name: str, choices, default=None):
    v = request.query_params.get(name)
    if v in (None, ""):
        return default
    if v not in choices:
        raise HTTPException(422, f"{name} must be one of {sorted(choices)}")
    return v


def token_of(request: Request) -> Optional[str]:
    return request.headers.get("x-org-token")


def otp_required() -> bool:
    return os.environ.get("BHOJAN_OTP_REQUIRED", "0").lower() in ("1", "true", "yes", "on")


def verify_otp(phone: str, code: str) -> bool:
    key = phone_key(normalize_indian_phone(phone))
    with connect() as c:
        row = c.execute("SELECT * FROM otp_requests WHERE phone_key=?", (key,)).fetchone()
        if not row:
            return False
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            c.execute("DELETE FROM otp_requests WHERE phone_key=?", (key,))
            return False
        if row["attempts"] >= 5:
            return False
        c.execute("UPDATE otp_requests SET attempts=attempts+1 WHERE phone_key=?", (key,))
        if otp_hash(code) != row["code_hash"]:
            return False
        c.execute("DELETE FROM otp_requests WHERE phone_key=?", (key,))
        return True


_ADMIN_TOKENS: dict[str, float] = {}


def admin_token_of(request: Request) -> Optional[str]:
    token = request.headers.get("x-admin-token")
    if token and _ADMIN_TOKENS.get(token, 0) > datetime.now(timezone.utc).timestamp():
        return token
    return None


def require_admin(request: Request):
    if not admin_token_of(request):
        raise HTTPException(401, "Admin login required")


def auth(conn, org_id: str, request: Request):
    row = conn.execute("SELECT * FROM orgs WHERE id=?", (org_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Profile not found")
    t = token_of(request)
    if not t or t != row["token"]:
        raise HTTPException(401, "Invalid or missing X-Org-Token")
    return row


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------- serializers
def public_org(row, lat=None, lng=None) -> dict:
    d = {"id": row["id"], "name": row["name"], "kind": row["kind"], "address": row["address"],
         "lat": row["lat"], "lng": row["lng"]}
    if row["kind"] != "INDIVIDUAL":  # never expose private individuals' numbers
        d["phone"] = row["phone"]
    if lat is not None and lng is not None:
        d["distance_km"] = round(haversine_km(lat, lng, row["lat"], row["lng"]), 2)
    return d


LISTING_SELECT = """SELECT l.*, o.name AS donor_name, o.kind AS donor_kind
                    FROM listings l JOIN orgs o ON o.id = l.org_id"""


def listing_out(r, lat=None, lng=None) -> dict:
    item = sl.BY_KEY.get(r["item_key"])
    expires, prepared = parse_ts(r["expires_at"]), parse_ts(r["prepared_at"])
    mins = int((expires - utcnow()).total_seconds() // 60)
    total_mins = int((expires - prepared).total_seconds() // 60)
    market, price = r["market_price_per_unit"], r["price_per_unit"]
    discount = round((1 - price / market) * 100) if market and market > 0 and price < market else None
    out = {
        "id": r["id"], "org_id": r["org_id"], "donor_name": r["donor_name"], "donor_kind": r["donor_kind"],
        "item_key": r["item_key"], "item_label": item.label if item else r["item_key"],
        "emoji": item.emoji if item else "🍽️", "group": item.group if item else "RAW",
        "title": r["title"], "description": r["description"], "is_veg": bool(r["is_veg"]),
        "quantity": r["quantity"], "quantity_left": r["quantity_left"], "unit": r["unit"],
        "price_per_unit": price, "market_price_per_unit": market, "is_free": price == 0,
        "discount_pct": discount, "storage": r["storage"],
        "prepared_at": prepared.isoformat(), "expires_at": expires.isoformat(),
        "total_shelf_minutes": total_mins,
        "minutes_left": mins, "freshness": sl.freshness(mins, total_mins),
        "address": r["address"], "lat": r["lat"], "lng": r["lng"], "status": r["status"],
        "created_at": r["created_at"],
    }
    if lat is not None and lng is not None:
        out["distance_km"] = round(haversine_km(lat, lng, r["lat"], r["lng"]), 2)
    return out


def claim_out(conn, c) -> dict:
    l = conn.execute(LISTING_SELECT + " WHERE l.id=?", (c["listing_id"],)).fetchone()
    donor = conn.execute("SELECT phone FROM orgs WHERE id=?", (l["org_id"],)).fetchone()
    rec = conn.execute("SELECT * FROM orgs WHERE id=?", (c["org_id"],)).fetchone()
    item = sl.BY_KEY.get(l["item_key"])
    return {
        "id": c["id"], "listing_id": c["listing_id"], "title": l["title"],
        "emoji": item.emoji if item else "🍽️", "unit": l["unit"], "quantity": c["quantity"],
        "total_price": c["total_price"], "code": c["code"], "status": c["status"],
        "created_at": c["created_at"], "expires_at": l["expires_at"],
        "minutes_left": int((parse_ts(l["expires_at"]) - utcnow()).total_seconds() // 60),
        "donor_name": l["donor_name"], "donor_phone": donor["phone"], "pickup_address": l["address"],
        "lat": l["lat"], "lng": l["lng"],
        "receiver_name": rec["name"], "receiver_kind": rec["kind"], "receiver_phone": rec["phone"],
    }


# ---------------------------------------------------------------- meta
async def health(request: Request):
    return JSONResponse({"status": "ok"})


async def catalog(request: Request):
    return JSONResponse({"items": sl.catalog_json(), "units": ["kg", "litres", "plates", "pieces"],
                         "storage_modes": list(sl.STORAGE_MODES)})


async def areas(request: Request):
    return JSONResponse({"city": AREA_DATA["city"], "also_called": AREA_DATA["also_called"],
                         "note": AREA_DATA["note"], "areas": AREAS})


# ---------------------------------------------------------------- orgs
async def register(request: Request):
    p = await read_body(request, OrgCreate)
    try:
        normalized_phone = normalize_indian_phone(p.phone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if otp_required() and not verify_otp(normalized_phone, p.otp):
        raise HTTPException(401, "Enter the correct 6-digit OTP sent to your mobile number")
    try:
        address, lat, lng = resolve_address(p.area, p.address, p.pincode, p.lat, p.lng, p.kind in DONOR_KINDS)
    except AddressError as e:
        raise HTTPException(422, str(e))
    oid, token = new_id("org"), uuid.uuid4().hex
    key = phone_key(normalized_phone)
    with connect() as c:
        if c.execute("SELECT 1 FROM orgs WHERE phone_key=?", (key,)).fetchone():
            raise HTTPException(409, "This phone number already has an account. Log in instead.")
        c.execute("INSERT INTO orgs (id, token, name, kind, phone, address, lat, lng, created_at, pw_hash, phone_key) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (oid, token, p.name.strip(), p.kind, normalized_phone, address,
                   lat, lng, utcnow().isoformat(), hash_password(p.password), key))
        row = c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone()
    return JSONResponse({**public_org(row), "phone": row["phone"], "token": token,
                         "can_donate": row["kind"] in DONOR_KINDS}, status_code=201)


async def login(request: Request):
    p = await read_body(request, LoginRequest)
    try:
        normalized_phone = normalize_indian_phone(p.phone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    key = phone_key(normalized_phone)
    if too_many_failures(key):
        raise HTTPException(429, "Too many wrong attempts. Try again in 10 minutes.")
    with connect() as c:
        row = c.execute("SELECT * FROM orgs WHERE phone_key=? AND phone_key != ''", (key,)).fetchone()
    otp_ok = bool(p.otp) and verify_otp(normalized_phone, p.otp)
    password_ok = bool(p.password) and row and row["pw_hash"] and verify_password(p.password, row["pw_hash"])
    if not row or not (otp_ok or password_ok):
        record_failure(key)
        raise HTTPException(401, "Phone number or password is wrong")
    clear_failures(key)
    return JSONResponse({**public_org(row), "phone": row["phone"], "token": row["token"],
                         "can_donate": row["kind"] in DONOR_KINDS})


async def request_otp(request: Request):
    p = await read_body(request, OTPRequest)
    try:
        phone = normalize_indian_phone(p.phone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    key = phone_key(phone)
    with connect() as c:
        exists = c.execute("SELECT 1 FROM orgs WHERE phone_key=?", (key,)).fetchone()
    if p.purpose == "signup" and exists:
        raise HTTPException(409, "This phone number already has an account. Log in instead.")
    if p.purpose == "login" and not exists:
        raise HTTPException(404, "No account found for this phone number")

    code = f"{secrets.randbelow(1000000):06d}"
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    with connect() as c:
        c.execute("INSERT INTO otp_requests (phone_key, code_hash, expires_at, attempts) "
                  "VALUES (?, ?, ?, 0) "
                  "ON CONFLICT(phone_key) DO UPDATE SET code_hash=excluded.code_hash, "
                  "expires_at=excluded.expires_at, attempts=0",
                  (key, otp_hash(code), expires.isoformat()))

    sms_sent = send_sms(phone, f"Your BhojanChain login code is {code}. It expires in 10 minutes.")
    result = {"status": "sent"}
    if sms_sent:
        return JSONResponse(result)
    if os.environ.get("BHOJAN_OTP_DEV", "0").lower() in ("1", "true", "yes", "on"):
        result["dev_otp"] = code
        return JSONResponse(result)
    raise HTTPException(503, "SMS OTP is not configured. Add Twilio settings in the server environment.")


async def admin_login(request: Request):
    p = await read_body(request, AdminLoginRequest)
    username = os.environ.get("BHOJAN_ADMIN_USERNAME", "")
    password = os.environ.get("BHOJAN_ADMIN_PASSWORD", "")
    if not username or not password or p.username != username or p.password != password:
        raise HTTPException(401, "Wrong admin username or password")
    token = secrets.token_urlsafe(32)
    _ADMIN_TOKENS[token] = datetime.now(timezone.utc).timestamp() + 8 * 3600
    return JSONResponse({"token": token})


async def admin_accounts(request: Request):
    require_admin(request)
    with connect() as c:
        rows = c.execute("SELECT id, name, kind, phone, address, lat, lng, created_at FROM orgs "
                         "ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            listings = c.execute("SELECT COUNT(*) FROM listings WHERE org_id=?", (r["id"],)).fetchone()[0]
            claims = c.execute("SELECT COUNT(*) FROM claims WHERE org_id=?", (r["id"],)).fetchone()[0]
            out.append({**dict(r), "listing_count": listings, "claim_count": claims})
    return JSONResponse(out)


async def admin_delete_account(request: Request):
    require_admin(request)
    org_id = request.path_params["org_id"]
    with connect() as c:
        row = c.execute("SELECT id, name FROM orgs WHERE id=?", (org_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Account not found")
        c.execute("DELETE FROM claims WHERE org_id=?", (org_id,))
        c.execute("DELETE FROM claims WHERE listing_id IN (SELECT id FROM listings WHERE org_id=?)", (org_id,))
        c.execute("DELETE FROM listings WHERE org_id=?", (org_id,))
        c.execute("DELETE FROM orgs WHERE id=?", (org_id,))
    return JSONResponse({"status": "deleted", "name": row["name"]})


async def nearby_orgs(request: Request):
    """Directory of NGOs, markets, wedding venues and restaurants around a point."""
    lat = q_float(request, "lat", lo=-90, hi=90)
    lng = q_float(request, "lng", lo=-180, hi=180)
    if lat is None or lng is None:
        raise HTTPException(422, "lat and lng are required")
    radius = q_float(request, "radius_km", default=10, gt=0, hi=200)
    kind = q_choice(request, "kind", KINDS - {"INDIVIDUAL"})
    with connect() as c:
        rows = c.execute("SELECT * FROM orgs WHERE kind != 'INDIVIDUAL'").fetchall()
    out = [public_org(r, lat, lng) for r in rows if not kind or r["kind"] == kind]
    out = sorted((o for o in out if o["distance_km"] <= radius), key=lambda o: o["distance_km"])
    return JSONResponse(out)


# ---------------------------------------------------------------- listings
async def create_listing(request: Request):
    org_id = request.path_params["org_id"]
    p = await read_body(request, ListingCreate)
    item = sl.BY_KEY.get(p.item_key)
    if not item:
        raise HTTPException(422, f"Unknown item_key '{p.item_key}'")
    if p.market_price_per_unit is not None and p.market_price_per_unit < p.price_per_unit:
        raise HTTPException(422, "Market price cannot be lower than your price")
    now = utcnow()
    prepared = p.prepared_at or now
    if prepared.tzinfo is None:
        prepared = prepared.replace(tzinfo=now.tzinfo)
    if prepared > now + timedelta(minutes=5):
        raise HTTPException(422, "prepared_at cannot be in the future")
    prepared = min(prepared, now)
    expires = sl.compute_expiry(item, prepared, p.storage, p.safe_hours_override)
    if expires <= now + timedelta(minutes=15):
        raise HTTPException(422, "This food has too little safe time left to list (under 15 minutes).")

    with connect() as c:
        org = auth(c, org_id, request)
        if org["kind"] not in DONOR_KINDS:
            raise HTTPException(403, "Only markets, wedding venues and restaurants can share surplus food")
        lid = new_id("lst")
        c.execute(
            "INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lid, org_id, p.item_key, (p.title or item.label).strip(), p.description.strip(),
             p.quantity, p.quantity, p.unit, p.price_per_unit, p.market_price_per_unit,
             int(item.veg if p.is_veg is None else p.is_veg), p.storage, prepared.isoformat(),
             expires.isoformat(), org["address"], org["lat"], org["lng"],
             "ACTIVE", now.isoformat()))
        row = c.execute(LISTING_SELECT + " WHERE l.id=?", (lid,)).fetchone()
    return JSONResponse(listing_out(row), status_code=201)


async def my_listings(request: Request):
    org_id = request.path_params["org_id"]
    with connect() as c:
        auth(c, org_id, request)
        rows = c.execute(LISTING_SELECT + " WHERE l.org_id=? ORDER BY l.created_at DESC", (org_id,)).fetchall()
    return JSONResponse([listing_out(r) for r in rows])


async def org_listings(request: Request):
    return await (create_listing(request) if request.method == "POST" else my_listings(request))


async def list_listings(request: Request):
    """Live, unexpired surplus listings. With lat/lng they are filtered to the radius and carry distance_km."""
    lat = q_float(request, "lat", lo=-90, hi=90)
    lng = q_float(request, "lng", lo=-180, hi=180)
    radius = q_float(request, "radius_km", default=10, gt=0, hi=200)
    group = q_choice(request, "group", {"COOKED", "RAW"})
    donor_kind = q_choice(request, "donor_kind", DONOR_KINDS)
    sort = q_choice(request, "sort", {"auto", "nearest", "soonest"}, "auto")
    veg_only, free_only = q_bool(request, "veg_only"), q_bool(request, "free_only")
    have_loc = lat is not None and lng is not None

    with connect() as c:
        rows = c.execute(LISTING_SELECT + " WHERE l.status='ACTIVE' AND l.quantity_left > 0 AND l.expires_at > ?",
                         (utcnow().isoformat(),)).fetchall()
    out = [listing_out(r, lat, lng) if have_loc else listing_out(r) for r in rows]
    out = [o for o in out if o["minutes_left"] > 0
           and (not have_loc or o["distance_km"] <= radius)
           and (not group or o["group"] == group)
           and (not veg_only or o["is_veg"])
           and (not free_only or o["is_free"])
           and (not donor_kind or o["donor_kind"] == donor_kind)]
    if have_loc and sort in ("auto", "nearest"):
        out.sort(key=lambda o: (o["distance_km"], o["minutes_left"]))
    else:
        out.sort(key=lambda o: o["minutes_left"])
    return JSONResponse(out)


async def get_listing(request: Request):
    with connect() as c:
        row = c.execute(LISTING_SELECT + " WHERE l.id=?", (request.path_params["listing_id"],)).fetchone()
    if not row:
        raise HTTPException(404, "Listing not found")
    return JSONResponse(listing_out(row))


async def close_listing(request: Request):
    org_id, lid = request.path_params["org_id"], request.path_params["listing_id"]
    with connect() as c:
        auth(c, org_id, request)
        cur = c.execute("UPDATE listings SET status='CLOSED' WHERE id=? AND org_id=?", (lid, org_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Listing not found")
    return JSONResponse({"status": "CLOSED"})


# ---------------------------------------------------------------- claims (reservations)
async def reserve(request: Request):
    listing_id = request.path_params["listing_id"]
    org_id = request.query_params.get("org_id")
    if not org_id:
        raise HTTPException(422, "org_id is required")
    p = await read_body(request, ClaimCreate)
    with connect() as c:
        me = auth(c, org_id, request)
        l = c.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        if not l or l["status"] != "ACTIVE":
            raise HTTPException(404, "Listing not available")
        if l["org_id"] == me["id"]:
            raise HTTPException(400, "You cannot reserve your own listing")
        if parse_ts(l["expires_at"]) <= utcnow():
            raise HTTPException(410, "This food is past its safe-to-eat time")
        # atomic decrement: fails if someone else took the stock first
        cur = c.execute("UPDATE listings SET quantity_left = quantity_left - ? "
                        "WHERE id=? AND quantity_left >= ?", (p.quantity, listing_id, p.quantity))
        if cur.rowcount == 0:
            left = c.execute("SELECT quantity_left FROM listings WHERE id=?", (listing_id,)).fetchone()[0]
            raise HTTPException(409, f"Only {left:g} {l['unit']} left")
        cid = new_id("clm")
        c.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)",
                  (cid, listing_id, me["id"], p.quantity, round(p.quantity * l["price_per_unit"], 2),
                   f"{random.randint(0, 9999):04d}", "RESERVED", utcnow().isoformat()))
        claim = c.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()
        return JSONResponse(claim_out(c, claim), status_code=201)


async def my_claims(request: Request):
    """Reservations I made (as NGO / individual)."""
    org_id = request.path_params["org_id"]
    with connect() as c:
        auth(c, org_id, request)
        rows = c.execute("SELECT * FROM claims WHERE org_id=? ORDER BY created_at DESC", (org_id,)).fetchall()
        return JSONResponse([claim_out(c, r) for r in rows])


async def incoming_claims(request: Request):
    """Reservations made on my listings (as donor)."""
    org_id = request.path_params["org_id"]
    with connect() as c:
        auth(c, org_id, request)
        rows = c.execute("""SELECT c.* FROM claims c JOIN listings l ON l.id=c.listing_id
                            WHERE l.org_id=? ORDER BY c.created_at DESC""", (org_id,)).fetchall()
        return JSONResponse([claim_out(c, r) for r in rows])


def set_claim(request: Request, action: str):
    org_id, claim_id = request.path_params["org_id"], request.path_params["claim_id"]
    with connect() as c:
        auth(c, org_id, request)
        cl = c.execute("SELECT c.*, l.org_id AS donor_id FROM claims c JOIN listings l ON l.id=c.listing_id "
                       "WHERE c.id=?", (claim_id,)).fetchone()
        if not cl:
            raise HTTPException(404, "Reservation not found")
        is_donor, is_receiver = cl["donor_id"] == org_id, cl["org_id"] == org_id
        if cl["status"] != "RESERVED":
            raise HTTPException(409, f"Reservation is already {cl['status']}")
        if action == "pickup":
            if not is_donor:
                raise HTTPException(403, "Only the donor can confirm pickup")
            c.execute("UPDATE claims SET status='PICKED_UP' WHERE id=?", (claim_id,))
        else:
            if not (is_donor or is_receiver):
                raise HTTPException(403, "Not your reservation")
            c.execute("UPDATE claims SET status='CANCELLED' WHERE id=?", (claim_id,))
            c.execute("UPDATE listings SET quantity_left = quantity_left + ? WHERE id=?",
                      (cl["quantity"], cl["listing_id"]))
        return JSONResponse(claim_out(c, c.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()))


async def mark_picked_up(request: Request):
    return set_claim(request, "pickup")


async def cancel_claim(request: Request):
    return set_claim(request, "cancel")


# ---------------------------------------------------------------- app
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@asynccontextmanager
async def lifespan(app):
    initialize_app()
    yield


def initialize_app():
    init_db()
    if os.environ.get("BHOJAN_SEED", "1") == "1":
        from seed import seed_if_empty
        seed_if_empty()


routes = [
    Route("/api/health", health),
    Route("/api/catalog", catalog),
    Route("/api/areas", areas),
    Route("/api/orgs", register, methods=["POST"]),
    Route("/api/login", login, methods=["POST"]),
    Route("/api/otp/request", request_otp, methods=["POST"]),
    Route("/api/admin/login", admin_login, methods=["POST"]),
    Route("/api/admin/accounts", admin_accounts),
    Route("/api/admin/accounts/{org_id}", admin_delete_account, methods=["DELETE"]),
    Route("/api/orgs/nearby", nearby_orgs),
    Route("/api/orgs/{org_id}/listings", org_listings, methods=["GET", "POST"]),
    Route("/api/orgs/{org_id}/listings/{listing_id}/close", close_listing, methods=["POST"]),
    Route("/api/orgs/{org_id}/claims", my_claims),
    Route("/api/orgs/{org_id}/incoming-claims", incoming_claims),
    Route("/api/orgs/{org_id}/claims/{claim_id}/pickup", mark_picked_up, methods=["POST"]),
    Route("/api/orgs/{org_id}/claims/{claim_id}/cancel", cancel_claim, methods=["POST"]),
    Route("/api/listings", list_listings),
    Route("/api/listings/{listing_id}", get_listing),
    Route("/api/listings/{listing_id}/claims", reserve, methods=["POST"]),
]
if FRONTEND.exists():  # mounted last so /api routes win
    routes.append(Mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend"))

app = Starlette(
    routes=routes,
    lifespan=lifespan,
    exception_handlers={HTTPException: http_error},
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
