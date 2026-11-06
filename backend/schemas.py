"""
schemas.py
----------
Pydantic models for request/response validation. Field-for-field mirrors
of the Farmer/Vehicle/Market dataclasses in logistics_lib_v2.py, per the
backend brief.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from logistics_lib_v2 import CROPS, VEHICLE_TYPES

VEHICLE_TYPE_NAMES = [t[0] for t in VEHICLE_TYPES]


# ---------- farmers ----------

class FarmerIn(BaseModel):
    lat: float
    lng: float
    crop: str
    qty_kg: float
    ready_hr: float
    deadline_hr: float
    # Optional on input: if omitted, derived from CROPS[crop] so callers
    # don't have to know the spoilage table by heart. Always populated
    # on output.
    needs_refrigeration: Optional[bool] = None

    @field_validator("crop")
    @classmethod
    def crop_known(cls, v: str) -> str:
        if v not in CROPS:
            raise ValueError(f"crop must be one of {list(CROPS)}")
        return v


class FarmerOut(BaseModel):
    id: int
    lat: float
    lng: float
    crop: str
    qty_kg: float
    ready_hr: float
    deadline_hr: float
    needs_refrigeration: bool


# ---------- vehicles ----------
# Vehicles are added by type_name; capacity_kg / refrigerated / fixed_cost /
# per_km_cost are derived from VEHICLE_TYPES (same lookup make_fleet() uses)
# so a vehicle's stated type and its physical/cost attributes can't drift
# apart. `count` lets a caller add several of the same type in one call.

class VehicleIn(BaseModel):
    type_name: str
    count: int = 1

    @field_validator("type_name")
    @classmethod
    def type_known(cls, v: str) -> str:
        if v not in VEHICLE_TYPE_NAMES:
            raise ValueError(f"type_name must be one of {VEHICLE_TYPE_NAMES}")
        return v

    @field_validator("count")
    @classmethod
    def count_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("count must be >= 1")
        return v


class VehicleOut(BaseModel):
    id: int
    type_name: str
    capacity_kg: float
    refrigerated: bool
    fixed_cost: float
    per_km_cost: float


# ---------- markets ----------

class MarketIn(BaseModel):
    lat: float
    lng: float
    price: Dict[str, float]
    capacity_kg: Dict[str, float]

    @field_validator("price", "capacity_kg")
    @classmethod
    def crops_known(cls, v: Dict[str, float]) -> Dict[str, float]:
        unknown = set(v) - set(CROPS)
        if unknown:
            raise ValueError(f"unknown crop(s) {sorted(unknown)}; must be a subset of {list(CROPS)}")
        return v


class MarketOut(BaseModel):
    id: int
    lat: float
    lng: float
    price: Dict[str, float]
    capacity_kg: Dict[str, float]


# ---------- sensor readings ----------
# pool_id: pool_result (per CONTRACT.md) has no persistent id of its own,
# so this is left as a free-form string. A reasonable convention is
# "<plan_run_id>:<vehicle_id>", but that's a hardware/frontend-team
# decision, not something this backend enforces.

class SensorReadingIn(BaseModel):
    pool_id: str
    temperature: float
    humidity: float
    timestamp: float


class SensorReadingOut(SensorReadingIn):
    id: int


class QuoteCheckIn(BaseModel):
    """A trader's doorstep offer for one farmer's whole lot, in Rs per kg."""
    farmer_id: int
    quote_per_kg: float = Field(gt=0)


class LoginIn(BaseModel):
    """Farmer login: the farmer's ID and the 6-digit PIN their FPO gave them."""
    farmer_id: int
    pin: str = Field(pattern=r"^\d{6}$")


class PhoneStartIn(BaseModel):
    """Farmer app: the number to text a code to, and the language to write messages in."""
    phone: str = Field(min_length=5, max_length=24)
    lang: str = Field(default="en", max_length=5)


class PhoneVerifyIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
