import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_tmp = tempfile.mkdtemp()
os.environ["BHOJAN_DB"] = os.path.join(_tmp, "test.db")
os.environ["BHOJAN_SEED"] = "0"

from starlette.testclient import TestClient  # noqa: E402

import shelf_life as sl  # noqa: E402
from db import parse_ts, utcnow  # noqa: E402
from main import app  # noqa: E402

MUMBAI = (15.8535, 74.5030)  # Khade Bazaar, Belagavi (name kept from the earlier tests)
PUNE = (15.8090, 74.5010)  # Udyambag, about 5 km away


@pytest.fixture()
def client(tmp_path):
    os.environ["BHOJAN_DB"] = str(tmp_path / "test.db")  # fresh database per test
    with TestClient(app) as c:
        yield c


AIRPORT = (15.8593, 74.6183)  # Sambra, about 11 km east


def reg(client, name, kind, loc=MUMBAI):
    area = {PUNE: "Udyambag", AIRPORT: "Sambra (Airport Road)"}.get(loc, "Khade Bazaar / Fort")
    r = client.post("/api/orgs", json={"name": name, "kind": kind, "phone": f"+91 98200{abs(hash(name)) % 100000:05d}", "password": "secret1", "area": area,
                                       "address": "Shop 5, near market gate", "lat": loc[0], "lng": loc[1]})
    assert r.status_code == 201, r.text
    d = r.json()
    return d["id"], {"X-Org-Token": d["token"]}


def post_listing(client, oid, h, **kw):
    body = {"item_key": "dal_curry", "quantity": 10, "unit": "plates", **kw}
    return client.post(f"/api/orgs/{oid}/listings", json=body, headers=h)


def test_catalog_has_cooked_and_raw(client):
    items = client.get("/api/catalog").json()["items"]
    groups = {i["group"] for i in items}
    assert groups == {"COOKED", "RAW"}
    assert all(i["room_h"] > 0 and i["cold_h"] >= i["room_h"] for i in items)


def test_expiry_from_shelf_life(client):
    oid, h = reg(client, "Hall", "WEDDING_VENUE")
    r = post_listing(client, oid, h)  # dal_curry room = 4h, prepared now
    assert r.status_code == 201
    body = r.json()
    assert 235 <= body["minutes_left"] <= 240
    assert body["freshness"] == "FRESH"
    assert body["is_free"] is True


def test_cold_storage_extends_and_override_only_shortens(client):
    oid, h = reg(client, "Hall", "WEDDING_VENUE")
    cold = post_listing(client, oid, h, storage="COLD").json()
    assert cold["minutes_left"] > 24 * 60
    short = post_listing(client, oid, h, safe_hours_override=1).json()
    assert short["minutes_left"] <= 60
    longer = post_listing(client, oid, h, safe_hours_override=100).json()  # capped to 4h
    assert longer["minutes_left"] <= 240


def test_already_expired_food_rejected(client):
    oid, h = reg(client, "Hall", "WEDDING_VENUE")
    old = (utcnow() - timedelta(hours=10)).isoformat()
    r = post_listing(client, oid, h, prepared_at=old)
    assert r.status_code == 422
    future = (utcnow() + timedelta(hours=2)).isoformat()
    assert post_listing(client, oid, h, prepared_at=future).status_code == 422


def test_only_donors_can_list_and_token_required(client):
    ngo, hn = reg(client, "NGO", "NGO")
    assert post_listing(client, ngo, hn).status_code == 403
    don, hd = reg(client, "Mandi", "MARKET_VENDOR")
    assert post_listing(client, don, {}).status_code == 401
    assert post_listing(client, don, {"X-Org-Token": "wrong"}).status_code == 401


def test_nearby_filter_and_distance_sort(client):
    near, hn = reg(client, "Near", "WEDDING_VENUE", MUMBAI)
    mid, hm = reg(client, "Mid", "RESTAURANT", PUNE)
    far, hf = reg(client, "Far", "MARKET_VENDOR", AIRPORT)
    for o, h in ((near, hn), (mid, hm), (far, hf)):
        post_listing(client, o, h)
    q = lambda r: [x["donor_name"] for x in client.get("/api/listings", params={"lat": MUMBAI[0], "lng": MUMBAI[1], "radius_km": r}).json()]  # noqa: E731
    assert q(3) == ["Near"]
    assert q(8) == ["Near", "Mid"]
    assert q(30) == ["Near", "Mid", "Far"]
    d = client.get("/api/orgs/nearby", params={"lat": MUMBAI[0], "lng": MUMBAI[1], "radius_km": 8}).json()
    assert [o["name"] for o in d] == ["Near", "Mid"]


def test_filters(client):
    oid, h = reg(client, "Mix", "MARKET_VENDOR")
    post_listing(client, oid, h, item_key="leafy_greens", unit="kg")
    post_listing(client, oid, h, item_key="raw_meat_fish", unit="kg", storage="COLD", price_per_unit=50)
    q = lambda **p: client.get("/api/listings", params=p).json()  # noqa: E731
    assert len(q(group="RAW")) == 2 and len(q(group="COOKED")) == 0
    assert len(q(veg_only=True)) == 1
    assert len(q(free_only=True)) == 1


def test_reserve_no_overselling_and_cancel_restores(client):
    don, hd = reg(client, "Hall", "WEDDING_VENUE")
    ngo, hn = reg(client, "NGO", "NGO")
    ngo2, hn2 = reg(client, "NGO2", "NGO")
    lid = post_listing(client, don, hd, quantity=10).json()["id"]

    r = client.post(f"/api/listings/{lid}/claims", params={"org_id": ngo}, json={"quantity": 7}, headers=hn)
    assert r.status_code == 201
    claim = r.json()
    assert len(claim["code"]) == 4 and claim["status"] == "RESERVED"
    assert claim["donor_phone"]

    over = client.post(f"/api/listings/{lid}/claims", params={"org_id": ngo2}, json={"quantity": 5}, headers=hn2)
    assert over.status_code == 409
    assert client.get(f"/api/listings/{lid}").json()["quantity_left"] == 3

    # cancelling gives stock back
    c = client.post(f"/api/orgs/{ngo}/claims/{claim['id']}/cancel", headers=hn)
    assert c.json()["status"] == "CANCELLED"
    assert client.get(f"/api/listings/{lid}").json()["quantity_left"] == 10
    # can't cancel twice
    assert client.post(f"/api/orgs/{ngo}/claims/{claim['id']}/cancel", headers=hn).status_code == 409


def test_pickup_permissions_and_sold_out_hides_listing(client):
    don, hd = reg(client, "Hall", "WEDDING_VENUE")
    ngo, hn = reg(client, "NGO", "NGO")
    lid = post_listing(client, don, hd, quantity=4).json()["id"]
    claim = client.post(f"/api/listings/{lid}/claims", params={"org_id": ngo}, json={"quantity": 4}, headers=hn).json()
    assert client.get("/api/listings").json() == []  # fully reserved -> not shown
    assert client.post(f"/api/orgs/{ngo}/claims/{claim['id']}/pickup", headers=hn).status_code == 403
    ok = client.post(f"/api/orgs/{don}/claims/{claim['id']}/pickup", headers=hd)
    assert ok.json()["status"] == "PICKED_UP"
    inc = client.get(f"/api/orgs/{don}/incoming-claims", headers=hd).json()
    assert inc[0]["receiver_name"] == "NGO"
    mine = client.get(f"/api/orgs/{ngo}/claims", headers=hn).json()
    assert mine[0]["code"] == claim["code"]


def test_paid_total_and_discount(client):
    don, hd = reg(client, "Hall", "RESTAURANT")
    ngo, hn = reg(client, "Person", "INDIVIDUAL")
    lst = post_listing(client, don, hd, price_per_unit=10, market_price_per_unit=40).json()
    assert lst["discount_pct"] == 75 and lst["is_free"] is False
    claim = client.post(f"/api/listings/{lst['id']}/claims", params={"org_id": ngo}, json={"quantity": 3}, headers=hn).json()
    assert claim["total_price"] == 30
    assert post_listing(client, don, hd, price_per_unit=50, market_price_per_unit=40).status_code == 422


def test_cannot_reserve_own_listing_and_individual_phone_hidden(client):
    don, hd = reg(client, "Hall", "RESTAURANT")
    lid = post_listing(client, don, hd).json()["id"]
    assert client.post(f"/api/listings/{lid}/claims", params={"org_id": don}, json={"quantity": 1}, headers=hd).status_code == 400
    reg(client, "Private Person", "INDIVIDUAL")
    d = client.get("/api/orgs/nearby", params={"lat": MUMBAI[0], "lng": MUMBAI[1], "radius_km": 50}).json()
    assert all(o["name"] != "Private Person" for o in d)


def test_freshness_levels():
    assert sl.freshness(0) == "EXPIRED"
    assert sl.freshness(60) == "URGENT"
    assert sl.freshness(180) == "USE_SOON"
    assert sl.freshness(900) == "FRESH"
    # a 4h-life dish is FRESH when new, USE_SOON once under half its life remains
    assert sl.freshness(235, 240) == "FRESH"
    assert sl.freshness(110, 240) == "USE_SOON"
    # long-life produce with 5h left of a 2-week window is still USE_SOON
    assert sl.freshness(300, 20160) == "USE_SOON"


def _org(**kw):
    return {"name": "Test Hall", "kind": "WEDDING_VENUE", "phone": "+91 9820011223", "password": "secret1", "area": "Tilakwadi",
            "address": "Main Road, near station", **kw}


def test_areas_listed(client):
    d = client.get("/api/areas").json()
    names = {a["name"] for a in d["areas"]}
    assert d["city"] == "Belagavi" and {"Tilakwadi", "Camp", "Shahapur"} <= names


def test_address_is_composed_and_geocoded_from_area(client):
    r = client.post("/api/orgs", json=_org(pincode="590006"))
    assert r.status_code == 201
    d = r.json()
    assert d["address"] == "Main Road, near station, Tilakwadi, Belagavi 590006"
    assert abs(d["lat"] - 15.8390) < 1e-6


@pytest.mark.parametrize("patch,msg", [
    ({"area": "Mumbai"}, "area"),
    ({"area": "Tilakwadi", "address": "x"}, "street"),
    ({"pincode": "400001"}, "Pincode"),
    ({"pincode": "59000"}, "Pincode"),
    ({"lat": 19.07, "lng": 72.87}, "outside Belagavi"),
    ({"lat": 15.9, "lng": 74.6}, "km from Tilakwadi"),
])
def test_bad_addresses_rejected(client, patch, msg):
    r = client.post("/api/orgs", json=_org(**patch))
    assert r.status_code == 422, r.text
    assert msg.lower() in r.text.lower()


def test_receiver_may_skip_street(client):
    r = client.post("/api/orgs", json=_org(kind="NGO", address=""))
    assert r.status_code == 201 and r.json()["address"] == "Tilakwadi, Belagavi"


def test_khasbag_and_spelling_alias(client):
    names = {a["name"] for a in client.get("/api/areas").json()["areas"]}
    assert {"Khasbag", "Shahapur"} <= names
    r = client.post("/api/orgs", json=_org(area="Shahpur"))
    assert r.status_code == 201 and "Shahapur" in r.json()["address"]


def test_login_roundtrip_and_duplicate_phone(client):
    r = client.post("/api/orgs", json=_org())
    assert r.status_code == 201
    first = r.json()
    # same number written differently is the same account
    dup = client.post("/api/orgs", json=_org(phone="09820011223"))
    assert dup.status_code == 409 and "Log in" in dup.text
    ok = client.post("/api/login", json={"phone": "98200 11223", "password": "secret1"})
    assert ok.status_code == 200
    assert ok.json()["id"] == first["id"] and ok.json()["token"] == first["token"]
    # the token from login really works
    assert client.get(f"/api/orgs/{first['id']}/claims", headers={"X-Org-Token": ok.json()["token"]}).status_code == 200


def test_wrong_password_and_throttle(client):
    client.post("/api/orgs", json=_org())
    bad = {"phone": "+91 9820011223", "password": "nope"}
    for _ in range(8):
        assert client.post("/api/login", json=bad).status_code == 401
    assert client.post("/api/login", json=bad).status_code == 429
    # even the right password is refused while throttled
    assert client.post("/api/login", json={**bad, "password": "secret1"}).status_code == 429
    from auth import clear_failures
    clear_failures("9820011223")


def test_unknown_phone_and_short_password(client):
    assert client.post("/api/login", json={"phone": "+91 9000012345", "password": "x"}).status_code == 401
    assert client.post("/api/orgs", json=_org(password="123")).status_code == 422
    assert client.post("/api/orgs", json=_org(phone="12345678")).status_code == 422


def test_valid_phone_and_dev_otp_signup_and_login(client, monkeypatch):
    monkeypatch.setenv("BHOJAN_OTP_REQUIRED", "1")
    monkeypatch.setenv("BHOJAN_OTP_DEV", "1")

    bad = client.post("/api/otp/request", json={"phone": "1234567890", "purpose": "signup"})
    assert bad.status_code == 422

    sent = client.post("/api/otp/request", json={"phone": "+91 9820011223", "purpose": "signup"})
    assert sent.status_code == 200
    code = sent.json()["dev_otp"]
    registered = client.post("/api/orgs", json=_org(otp=code))
    assert registered.status_code == 201

    login_sent = client.post("/api/otp/request", json={"phone": "9820011223", "purpose": "login"})
    login_code = login_sent.json()["dev_otp"]
    logged_in = client.post("/api/login", json={"phone": "9820011223", "otp": login_code})
    assert logged_in.status_code == 200
    assert logged_in.json()["id"] == registered.json()["id"]


def test_admin_can_list_and_delete_account(client, monkeypatch):
    monkeypatch.setenv("BHOJAN_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("BHOJAN_ADMIN_PASSWORD", "admin-secret")
    account = client.post("/api/orgs", json=_org(name="Delete Me")).json()

    denied = client.get("/api/admin/accounts")
    assert denied.status_code == 401
    login = client.post("/api/admin/login", json={"username": "admin", "password": "admin-secret"})
    assert login.status_code == 200
    headers = {"X-Admin-Token": login.json()["token"]}

    accounts = client.get("/api/admin/accounts", headers=headers).json()
    assert any(a["id"] == account["id"] for a in accounts)
    deleted = client.delete(f"/api/admin/accounts/{account['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert client.get("/api/admin/accounts", headers=headers).json() == []


def test_passwords_are_not_stored_plain(client):
    client.post("/api/orgs", json=_org())
    from db import connect
    with connect() as c:
        h = c.execute("SELECT pw_hash FROM orgs").fetchone()[0]
    assert h.startswith("scrypt$") and "secret1" not in h
