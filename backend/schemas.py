from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

OrgKind = Literal["MARKET_VENDOR", "WEDDING_VENUE", "RESTAURANT", "NGO", "INDIVIDUAL"]
DONOR_KINDS = {"MARKET_VENDOR", "WEDDING_VENUE", "RESTAURANT"}
Unit = Literal["kg", "litres", "plates", "pieces"]


class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: OrgKind
    phone: str = Field(min_length=7, max_length=20)
    password: str = Field(min_length=6, max_length=72)
    area: str = Field(min_length=2, max_length=60)  # one of the Belagavi areas
    address: str = Field(default="", max_length=200)  # street / shop / landmark
    pincode: Optional[str] = Field(default=None, max_length=6)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)  # optional exact map pin
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


class ListingCreate(BaseModel):
    item_key: str
    title: Optional[str] = Field(default=None, max_length=80)
    description: str = Field(default="", max_length=300)
    quantity: float = Field(gt=0, le=100000)
    unit: Unit = "kg"
    price_per_unit: float = Field(default=0, ge=0, le=100000)  # 0 = free
    market_price_per_unit: Optional[float] = Field(default=None, ge=0, le=100000)
    storage: Literal["ROOM", "COLD"] = "ROOM"
    prepared_at: Optional[datetime] = None  # when cooked / bought; defaults to now
    safe_hours_override: Optional[float] = Field(default=None, gt=0)  # may only shorten
    is_veg: Optional[bool] = None  # defaults to the catalog value
    address: Optional[str] = Field(default=None, max_length=200)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


class ClaimCreate(BaseModel):
    quantity: float = Field(gt=0)


class LoginRequest(BaseModel):
    phone: str = Field(min_length=7, max_length=20)
    password: str = Field(min_length=1, max_length=72)
