"""
logistics_lib_v2.py
--------------------
v2 data model. Changes from v1, all driven by the audit of the original
prototype:

  1. Vehicles are now real INSTANCES with an id, drawn from a fleet
     composition (e.g. "12 of type A, 6 of type B, ..."). Fleet size is
     finite and enforced at assignment time in algorithms_v2.py -- v1
     let an unlimited number of "vehicles" dispatch simultaneously,
     which the audit flagged as the single biggest gap between the
     stated assumptions and the actual behavior.
  2. 6 crops instead of 2, covering a wider spoilage/refrigeration
     spectrum (leafy greens spoil fast even refrigerated; potato is
     forgiving).
  3. 7 vehicle types instead of 4 (small pickup -> large reefer truck).
  4. Markets can optionally have elastic pricing (price steps down as
     a market fills up this cycle) instead of a flat price up to a
     hard capacity cliff.
"""

import math
import random
from dataclasses import dataclass, field

AVG_SPEED_KMPH = 32
DISPATCH_OVERHEAD_HR = 0.5
STOP_OVERHEAD_HR = 0.15
# Buffer added after a vehicle finishes its dropoff run before it's
# considered available for a second trip that day (unload, refuel,
# paperwork, drive back toward the pickup area). This is a simplification
# -- a real system would route the empty return leg -- but it's enough
# to make multi-trip reuse directionally realistic for a POC.
TURNAROUND_HR = 1.0
WORKDAY_END_HR = 14.0  # vehicles won't start a fresh trip after this

CROPS = {
    "tomato":      {"needs_refrigeration": True,  "base_spoil_per_hr": 0.020},
    "onion":       {"needs_refrigeration": False, "base_spoil_per_hr": 0.008},
    "potato":      {"needs_refrigeration": False, "base_spoil_per_hr": 0.005},
    "cauliflower": {"needs_refrigeration": True,  "base_spoil_per_hr": 0.018},
    "mango":       {"needs_refrigeration": True,  "base_spoil_per_hr": 0.014},
    "spinach":     {"needs_refrigeration": True,  "base_spoil_per_hr": 0.035},
}

# (name, capacity_kg, refrigerated, fixed_cost_inr, per_km_cost_inr)
VEHICLE_TYPES = [
    ("mini_pickup",      500,  False,  500, 14),
    ("van",              1000, False,  900, 18),
    ("reefer_van",       1000, True,  1300, 21),
    ("truck_2t",         2000, False, 1700, 20),
    ("reefer_2t",        2000, True,  2200, 24),
    ("truck_5t",         5000, False, 3200, 27),
    ("reefer_5t",        5000, True,  4000, 32),
]


@dataclass
class Farmer:
    id: int
    lat: float
    lng: float
    crop: str
    qty_kg: float
    ready_hr: float
    deadline_hr: float
    needs_refrigeration: bool


@dataclass
class Vehicle:
    id: int
    type_name: str
    capacity_kg: float
    refrigerated: bool
    fixed_cost: float
    per_km_cost: float
    available_at_hr: float = 0.0   # mutated during assignment (real fleet state)


@dataclass
class Market:
    id: int
    lat: float
    lng: float
    price: dict         # crop -> base ₹/kg
    capacity_kg: dict    # crop -> kg absorbed this cycle


def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def spoilage_fraction(crop, vehicle_refrigerated, transit_hours):
    info = CROPS[crop]
    rate = info["base_spoil_per_hr"]
    if info["needs_refrigeration"] and not vehicle_refrigerated:
        rate *= 3.0
    return min(rate * transit_hours, 0.6)


def make_fleet(fleet_composition, seed=0):
    """fleet_composition: dict {type_name: count}. Returns a list of
    Vehicle instances -- this is the actual, finite fleet."""
    rng = random.Random(seed)
    by_name = {t[0]: t for t in VEHICLE_TYPES}
    fleet = []
    vid = 0
    for type_name, count in fleet_composition.items():
        _, cap, refrig, fc, pk = by_name[type_name]
        for _ in range(count):
            fleet.append(Vehicle(id=vid, type_name=type_name, capacity_kg=cap,
                                  refrigerated=refrig, fixed_cost=fc, per_km_cost=pk))
            vid += 1
    return fleet


def default_fleet_composition(n_farmers):
    """Scales a plausible fleet with farmer count -- roughly 1 vehicle
    per 40 farmers, split across types, skewed toward mid-size trucks.
    This is a judgment call for the POC, not a measured ratio."""
    n_vehicles = max(4, round(n_farmers / 40))
    weights = {"mini_pickup": 0.10, "van": 0.20, "reefer_van": 0.10,
               "truck_2t": 0.25, "reefer_2t": 0.15, "truck_5t": 0.13, "reefer_5t": 0.07}
    comp = {name: max(0, round(n_vehicles * w)) for name, w in weights.items()}
    if sum(comp.values()) == 0:
        comp["van"] = 1
    return comp


def generate_scenario_v2(n_farmers=20, n_markets=3, fleet_composition=None, seed=0,
                          elastic_pricing=False, tranches=3):
    rng = random.Random(seed)
    center_lat, center_lng = 25.60, 84.90
    half_deg = 0.18 * max(1.0, math.sqrt(n_farmers / 20))  # area grows a bit with farmer count

    crop_names = list(CROPS.keys())
    farmers = []
    for i in range(n_farmers):
        crop = rng.choices(crop_names, weights=[3, 2, 2, 2, 1.5, 1.5])[0]
        ready = rng.uniform(0, 4)
        farmers.append(Farmer(
            id=i,
            lat=center_lat + rng.uniform(-half_deg, half_deg),
            lng=center_lng + rng.uniform(-half_deg, half_deg),
            crop=crop,
            qty_kg=rng.uniform(150, 600),
            ready_hr=ready,
            deadline_hr=ready + rng.uniform(6, 14),
            needs_refrigeration=CROPS[crop]["needs_refrigeration"],
        ))

    if fleet_composition is None:
        fleet_composition = default_fleet_composition(n_farmers)
    vehicles = make_fleet(fleet_composition, seed=seed)

    markets = []
    for m in range(n_markets):
        dist_bias = rng.uniform(0.15, 0.55) * max(1.0, math.sqrt(n_farmers / 20))
        markets.append(Market(
            id=m,
            lat=center_lat + rng.uniform(-1, 1) * dist_bias,
            lng=center_lng + rng.uniform(-1, 1) * dist_bias,
            price={c: round(rng.uniform(*_PRICE_RANGE[c]), 2) for c in crop_names},
            capacity_kg={c: rng.uniform(2500, 6000) for c in crop_names},
        ))

    return farmers, vehicles, markets


_PRICE_RANGE = {
    "tomato": (14, 26), "onion": (9, 18), "potato": (7, 13),
    "cauliflower": (10, 20), "mango": (25, 45), "spinach": (12, 22),
}


def market_demand_nodes(markets, crop, elastic_pricing, tranches=3):
    """Expands each market into 1 (flat price) or `tranches` (elastic
    price) demand nodes for the allocation LP. Elastic tranches: price
    steps down as the market fills up this cycle -- a simple
    piecewise-linear stand-in for a real demand curve.
    """
    nodes = []
    tranche_shares = [0.5, 0.3, 0.2][:tranches]
    tranche_price_mult = [1.0, 0.90, 0.78][:tranches]
    for m in markets:
        cap = m.capacity_kg[crop]
        price = m.price[crop]
        if not elastic_pricing:
            nodes.append({"market": m, "capacity_kg": cap, "price": price})
        else:
            for share, mult in zip(tranche_shares, tranche_price_mult):
                nodes.append({"market": m, "capacity_kg": cap * share, "price": price * mult})
    return nodes


def fresh_capacity(markets):
    return {m.id: dict(m.capacity_kg) for m in markets}
