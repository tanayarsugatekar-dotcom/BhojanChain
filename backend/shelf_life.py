"""Shelf-life rules for BhojanChain.

Hours are CONSERVATIVE food-safety guidelines, counted from the moment the food was
cooked (cooked items) or bought/harvested (raw items):

  room_h : hours it stays safe kept at normal Indian room temperature (or hot-held)
  cold_h : hours it stays safe in a fridge / cold storage (<= 5 C)

They are guidance, not a guarantee. Receivers should still check smell, look and
texture before eating. Donors may only *shorten* a limit, never extend it.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class FoodItem:
    key: str
    label: str
    group: str  # COOKED | RAW
    emoji: str
    room_h: float
    cold_h: float
    default_unit: str
    veg: bool = True
    note: str = ""


H = 1
D = 24

CATALOG: list[FoodItem] = [
    # ---- Cooked (wedding venues, restaurants, dhabas) ----
    FoodItem("cooked_rice", "Cooked rice / biryani / pulao", "COOKED", "🍚", 4, 24, "plates", True,
             "Reheat until steaming hot before serving."),
    FoodItem("dal_curry", "Dal / curry / sabzi", "COOKED", "🍛", 4, 36, "plates", True),
    FoodItem("roti", "Roti / chapati / paratha / puri", "COOKED", "🫓", 8, 48, "pieces", True),
    FoodItem("fried_snacks", "Fried snacks (samosa, pakora)", "COOKED", "🥟", 6, 24, "pieces", True),
    FoodItem("milk_sweets", "Milk sweets (rasgulla, barfi, kheer)", "COOKED", "🍮", 6, 48, "kg", True),
    FoodItem("dry_sweets", "Dry sweets (laddu, mysore pak)", "COOKED", "🍬", 48, 168, "kg", True),
    FoodItem("non_veg_cooked", "Cooked chicken / mutton / fish", "COOKED", "🍗", 2, 36, "plates", False,
             "High-risk: keep hot (>60 C) or refrigerate quickly."),
    FoodItem("salad_raita", "Salad / raita / chutney", "COOKED", "🥗", 2, 24, "kg", True),
    FoodItem("buffet_mixed", "Mixed wedding buffet leftovers", "COOKED", "🍽️", 3, 24, "plates", True,
             "Use the shortest-life dish in the mix."),
    # ---- Raw (markets, mandi vendors, grocers) ----
    FoodItem("leafy_greens", "Leafy greens (palak, methi, coriander)", "RAW", "🥬", 12, 72, "kg"),
    FoodItem("tomato", "Tomatoes", "RAW", "🍅", 4 * D, 7 * D, "kg"),
    FoodItem("onion_potato", "Onions / potatoes", "RAW", "🧅", 14 * D, 30 * D, "kg"),
    FoodItem("veg_other", "Other vegetables (beans, gourds, cauliflower)", "RAW", "🥦", 2 * D, 5 * D, "kg"),
    FoodItem("fruit_soft", "Soft fruit (banana, papaya, mango, berries)", "RAW", "🍌", 2 * D, 4 * D, "kg"),
    FoodItem("fruit_hard", "Hard fruit (apple, orange, pomegranate)", "RAW", "🍎", 7 * D, 21 * D, "kg"),
    FoodItem("milk", "Milk (pasteurised)", "RAW", "🥛", 2, 2 * D, "litres"),
    FoodItem("curd", "Curd / yogurt", "RAW", "🥣", 6, 5 * D, "kg"),
    FoodItem("paneer", "Paneer", "RAW", "🧀", 4, 5 * D, "kg"),
    FoodItem("bread_bakery", "Bread / pav / bakery items", "RAW", "🍞", 3 * D, 7 * D, "pieces"),
    FoodItem("eggs", "Eggs", "RAW", "🥚", 2 * D, 21 * D, "pieces", False),
    FoodItem("raw_meat_fish", "Raw chicken / meat / fish", "RAW", "🥩", 2, 36, "kg", False,
             "Must stay refrigerated; do not list if it has been out for > 2 hours."),
    FoodItem("dry_grains", "Dry grains, pulses, flour", "RAW", "🌾", 90 * D, 180 * D, "kg"),
]

BY_KEY = {i.key: i for i in CATALOG}
STORAGE_MODES = ("ROOM", "COLD")


def catalog_json() -> list[dict]:
    return [asdict(i) for i in CATALOG]


def safe_hours(item: FoodItem, storage: str, override: Optional[float] = None) -> float:
    base = item.cold_h if storage == "COLD" else item.room_h
    if override is not None:
        return min(base, override)  # donors can shorten, never extend
    return base


def compute_expiry(item: FoodItem, prepared_at: datetime, storage: str,
                   override: Optional[float] = None) -> datetime:
    return prepared_at + timedelta(hours=safe_hours(item, storage, override))


def freshness(minutes_left: float, total_minutes: Optional[float] = None) -> str:
    """EXPIRED | URGENT | USE_SOON | FRESH

    URGENT   : 90 minutes or less of safe time left
    USE_SOON : under 6 hours left AND less than half of the item's safe window remaining
    FRESH    : otherwise (e.g. food just cooked, or long-life produce)
    """
    if minutes_left <= 0:
        return "EXPIRED"
    if minutes_left <= 90:
        return "URGENT"
    if minutes_left <= 6 * 60:
        if total_minutes is None or minutes_left < total_minutes * 0.5:
            return "USE_SOON"
    return "FRESH"
