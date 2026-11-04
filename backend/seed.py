"""Demo data around Mumbai so the app is not empty on first run. Disable with BHOJAN_SEED=0."""
import uuid
from datetime import timedelta

from db import connect, phone_key, utcnow
import shelf_life as sl

ORGS = [
    # id, name, kind, phone, address, lat, lng  (demo data: invented names and placeholder phone numbers)
    ("org-demo-v1", "Khade Bazaar Sabzi Stall 14 (demo)", "MARKET_VENDOR", "+91 90000 00001", "Stall 14, Khade Bazaar / Fort, Belagavi 590002", 15.8535, 74.5030),
    ("org-demo-v2", "Kapileshwar Road Fruit Traders (demo)", "MARKET_VENDOR", "+91 90000 00002", "Near Kapileshwar Temple, Kapileshwar Road, Belagavi 590001", 15.8440, 74.5040),
    ("org-demo-v3", "Shubh Mangal Karyalaya (demo)", "WEDDING_VENUE", "+91 90000 00003", "Main Road, Tilakwadi, Belagavi 590006", 15.8390, 74.5130),
    ("org-demo-v4", "Vijay Lawns & Banquet (demo)", "WEDDING_VENUE", "+91 90000 00004", "Congress Road, Camp, Belagavi 590001", 15.8640, 74.5180),
    ("org-demo-v5", "Udyambag Dhaba (demo)", "RESTAURANT", "+91 90000 00005", "Industrial Estate Road, Udyambag, Belagavi 590008", 15.8090, 74.5010),
    ("org-demo-n1", "Annadaan Seva Trust (demo)", "NGO", "+91 90000 00011", "Near Bus Stop, Shahapur, Belagavi 590003", 15.8330, 74.4960),
    ("org-demo-n2", "Roti Bank Belagavi (demo)", "NGO", "+91 90000 00012", "Mahantesh Nagar, Belagavi 590016", 15.8780, 74.5230),
    ("org-demo-n3", "Umeed Child Care Centre (demo)", "NGO", "+91 90000 00013", "Sadashiv Nagar, Belagavi 590019", 15.8700, 74.5100),
]

# org, item_key, title, qty, unit, price, market_price, storage, hours_ago, description
LISTINGS = [
    ("org-demo-v1", "leafy_greens", "Palak & methi bundles", 18.5, "kg", 0, 40, "ROOM", 6, "Fresh this morning, a bit wilted but fine for cooking."),
    ("org-demo-v1", "tomato", "Ripe tomatoes", 25, "kg", 8, 30, "ROOM", 30, "Soft, best for gravies and chutney."),
    ("org-demo-v2", "fruit_soft", "Bananas & papaya", 40, "kg", 0, 50, "ROOM", 40, "Over-ripe, great for shakes and sheera."),
    ("org-demo-v3", "buffet_mixed", "Wedding dinner leftovers (veg)", 120, "plates", 0, None, "ROOM", 1.2, "Rice, sambar, palya, chapati, sweet. Packed hot in foil boxes."),
    ("org-demo-v3", "milk_sweets", "Payasa & Mysore pak", 15, "kg", 0, None, "COLD", 2, "Kept in cold room since service."),
    ("org-demo-v4", "cooked_rice", "Veg pulao", 60, "plates", 15, 120, "ROOM", 2.5, "Hot-held; pick up within the hour."),
    ("org-demo-v5", "roti", "Jolada rotti", 150, "pieces", 0, 10, "ROOM", 1, "Packed in clean paper."),
    ("org-demo-v5", "dal_curry", "Dal fry", 35, "plates", 10, 90, "ROOM", 2, "Cooked at lunch service."),
]


def seed_if_empty() -> None:
    now = utcnow()
    with connect() as c:
        if c.execute("SELECT COUNT(*) FROM orgs").fetchone()[0]:
            return
        for oid, name, kind, phone, addr, lat, lng in ORGS:
            c.execute("INSERT INTO orgs (id, token, name, kind, phone, address, lat, lng, created_at, phone_key) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (oid, uuid.uuid4().hex, name, kind, phone, addr, lat, lng, now.isoformat(), phone_key(phone)))
        orgs = {o[0]: o for o in ORGS}
        for oid, key, title, qty, unit, price, market, storage, hrs, desc in LISTINGS:
            item = sl.BY_KEY[key]
            prepared = now - timedelta(hours=hrs)
            expires = sl.compute_expiry(item, prepared, storage)
            if expires <= now + timedelta(minutes=20):  # keep demo items alive
                prepared = now - timedelta(hours=max(0.0, (item.room_h if storage == "ROOM" else item.cold_h) * 0.5))
                expires = sl.compute_expiry(item, prepared, storage)
            o = orgs[oid]
            c.execute("INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (f"lst-{uuid.uuid4().hex[:8]}", oid, key, title, desc, qty, qty, unit, price, market,
                       int(item.veg), storage, prepared.isoformat(), expires.isoformat(),
                       o[4], o[5], o[6], "ACTIVE", now.isoformat()))
