import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def db_path() -> str:
    return os.environ.get("BHOJAN_DB", str(Path(__file__).parent / "bhojanchain.db"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    id         TEXT PRIMARY KEY,
    token      TEXT NOT NULL,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('MARKET_VENDOR','WEDDING_VENUE','RESTAURANT','NGO','INDIVIDUAL')),
    phone      TEXT NOT NULL,
    address    TEXT NOT NULL DEFAULT '',
    lat        REAL NOT NULL,
    lng        REAL NOT NULL,
    created_at TEXT NOT NULL,
    pw_hash    TEXT NOT NULL DEFAULT '',
    phone_key  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS listings (
    id                   TEXT PRIMARY KEY,
    org_id               TEXT NOT NULL REFERENCES orgs(id),
    item_key             TEXT NOT NULL,
    title                TEXT NOT NULL,
    description          TEXT NOT NULL DEFAULT '',
    quantity             REAL NOT NULL CHECK (quantity > 0),
    quantity_left        REAL NOT NULL CHECK (quantity_left >= 0),
    unit                 TEXT NOT NULL,
    price_per_unit       REAL NOT NULL DEFAULT 0 CHECK (price_per_unit >= 0),
    market_price_per_unit REAL,
    is_veg               INTEGER NOT NULL DEFAULT 1,
    storage              TEXT NOT NULL CHECK (storage IN ('ROOM','COLD')),
    prepared_at          TEXT NOT NULL,
    expires_at           TEXT NOT NULL,
    address              TEXT NOT NULL DEFAULT '',
    lat                  REAL NOT NULL,
    lng                  REAL NOT NULL,
    status               TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','CLOSED')),
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(status, expires_at);

CREATE TABLE IF NOT EXISTS claims (
    id          TEXT PRIMARY KEY,
    listing_id  TEXT NOT NULL REFERENCES listings(id),
    org_id      TEXT NOT NULL REFERENCES orgs(id),
    quantity    REAL NOT NULL CHECK (quantity > 0),
    total_price REAL NOT NULL DEFAULT 0,
    code        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'RESERVED' CHECK (status IN ('RESERVED','PICKED_UP','CANCELLED')),
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_listing ON claims(listing_id);
CREATE INDEX IF NOT EXISTS idx_claims_org ON claims(org_id);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def phone_key(phone: str) -> str:
    """Last 10 digits, so '+91 98200-11223' and '09820011223' are the same account."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-10:]


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(orgs)")}
        if "pw_hash" not in cols:  # database created by an older version
            c.execute("ALTER TABLE orgs ADD COLUMN pw_hash TEXT NOT NULL DEFAULT ''")
        if "phone_key" not in cols:
            c.execute("ALTER TABLE orgs ADD COLUMN phone_key TEXT NOT NULL DEFAULT ''")
            for r in c.execute("SELECT id, phone FROM orgs").fetchall():
                c.execute("UPDATE orgs SET phone_key=? WHERE id=?", (phone_key(r["phone"]), r["id"]))
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orgs_phone ON orgs(phone_key) WHERE phone_key != ''")
