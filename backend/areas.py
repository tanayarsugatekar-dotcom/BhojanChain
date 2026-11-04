"""Belagavi (Belgaum) areas and address checking. Data lives in belagavi_areas.json (shared with the web app)."""
import json
import re
from pathlib import Path

from geo import haversine_km

DATA = json.loads((Path(__file__).parent / "belagavi_areas.json").read_text(encoding="utf-8"))
AREAS = DATA["areas"]
BY_NAME = {n.lower(): a for a in AREAS for n in [a["name"], *a.get("aliases", [])]}
PIN_RE = re.compile(r"^59[01]\d{3}$")  # Belagavi district pincodes


class AddressError(ValueError):
    pass


def resolve_address(area, street, pincode, lat, lng, required_street):
    """Return (full_address, lat, lng) or raise AddressError with a message the user can act on."""
    a = BY_NAME.get((area or "").strip().lower())
    if not a:
        raise AddressError("Choose your area of Belagavi from the list")
    street = " ".join((street or "").split())
    if required_street and (len(street) < 5 or not re.search(r"[A-Za-zಀ-೿]", street)):
        raise AddressError("Enter a street, shop or landmark (at least 5 characters), e.g. 'Shop 14, near Kapileshwar Temple'")
    pincode = (pincode or "").strip()
    if pincode and not PIN_RE.match(pincode):
        raise AddressError("Pincode must be 6 digits and start with 590 or 591 (Belagavi), e.g. 590006")
    if lat is None or lng is None:
        lat, lng = a["lat"], a["lng"]
    b = DATA["bbox"]
    if not (b["lat"][0] <= lat <= b["lat"][1] and b["lng"][0] <= lng <= b["lng"][1]):
        raise AddressError("That location is outside Belagavi")
    d = haversine_km(lat, lng, a["lat"], a["lng"])
    if d > DATA["max_pin_distance_km"]:
        raise AddressError(f"The map pin is {d:.1f} km from {a['name']}. Pick the area the pin is in.")
    parts = [street, a["name"], f"Belagavi {pincode}".strip()]
    return ", ".join(p for p in parts if p), lat, lng
