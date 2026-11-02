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
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

try:
    from sklearn.cluster import KMeans
    _HAVE_SKLEARN = True
except ImportError:
    _HAVE_SKLEARN = False

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


# ----------------------------------------------------------------------
# Road-distance model. Every planner distance goes through haversine(), which now returns
#   ROAD_CIRCUITY x great-circle km
# (road km ~ circuity x straight-line km; time follows because time = km / AVG_SPEED_KMPH).
# Default 1.0 = the legacy straight-line model, so existing benchmarks are unchanged. Set it from a
# calibration (see calibrate_circuity.py) with set_road_circuity(), the road_circuity() context manager, or the
# FARMROUTE_ROAD_CIRCUITY environment variable. Radius thresholds in km (clustering eps, neighbour radius) are
# road-km: callers convert them to straight-line km with get_road_circuity().
# ----------------------------------------------------------------------
import contextlib
import os

ROAD_CIRCUITY = float(os.environ.get("FARMROUTE_ROAD_CIRCUITY", "1.0"))


def _check_circuity(k):
    k = float(k)
    if not (1.0 <= k <= 3.0):
        raise ValueError(f"road circuity must be in [1, 3], got {k}")
    return k


ROAD_CIRCUITY = _check_circuity(ROAD_CIRCUITY)


# ----------------------------------------------------------------------
# Measured road distances. When a RoadMatrix is active (use_road_matrix()), haversine() returns the real road km
# between two of its points instead of circuity x straight-line, so every cost, time, deadline and spoilage
# figure the planner computes follows real roads. Pairs the matrix does not know fall back to circuity x
# straight-line, using the matrix's own measured ratio (also what radius/clustering thresholds are scaled by).
# Context-local (contextvars), so concurrent requests never see each other's matrix. Default = no matrix, which
# leaves every existing behaviour and benchmark unchanged.
# ----------------------------------------------------------------------
import contextvars

_ROAD_MATRIX = contextvars.ContextVar("road_matrix", default=None)


class RoadMatrix:
    """index: {(lat, lng): row} for every point (several exact points may share a row);
    km: square matrix of road km between rows (None/NaN = unknown); ratio: median road/straight, used as fallback."""

    def __init__(self, index, km, ratio):
        self.index = dict(index)
        self.rows = [[(float("nan") if v is None else float(v)) for v in r] for r in km]
        self.ratio = _check_circuity(ratio)

    def get(self, lat1, lng1, lat2, lng2):
        i = self.index.get((lat1, lng1))
        if i is None:
            return None
        j = self.index.get((lat2, lng2))
        if j is None:
            return None
        v = self.rows[i][j]
        return None if v != v else v

    def override_vec(self, base, lat1, lng1, lat2, lng2):
        """`base` (numpy, already circuity-scaled straight-line km) with every known pair replaced by its road km."""
        import numpy as np
        la1, ln1, la2, ln2 = np.broadcast_arrays(lat1, lng1, lat2, lng2)
        out = np.array(np.broadcast_to(base, la1.shape), dtype=float)
        flat = out.reshape(-1)
        for k, (a, b, c, d) in enumerate(zip(la1.reshape(-1), ln1.reshape(-1), la2.reshape(-1), ln2.reshape(-1))):
            v = self.get(a, b, c, d)
            if v is not None:
                flat[k] = v
        return out


@contextlib.contextmanager
def use_road_matrix(matrix):
    """Plan/evaluate with measured road distances (restores the previous state on exit)."""
    token = _ROAD_MATRIX.set(matrix)
    try:
        yield
    finally:
        _ROAD_MATRIX.reset(token)


def get_road_matrix():
    return _ROAD_MATRIX.get()


def get_road_circuity():
    m = _ROAD_MATRIX.get()
    return m.ratio if m is not None else ROAD_CIRCUITY


def set_road_circuity(k):
    global ROAD_CIRCUITY
    ROAD_CIRCUITY = _check_circuity(k)


@contextlib.contextmanager
def road_circuity(k):
    """Temporarily plan/evaluate with a different road circuity (restores the previous value on exit)."""
    global ROAD_CIRCUITY
    prev, ROAD_CIRCUITY = ROAD_CIRCUITY, _check_circuity(k)
    try:
        yield
    finally:
        ROAD_CIRCUITY = prev


def crow_km(lat1, lng1, lat2, lng2):
    """Great-circle (straight-line) km."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def haversine(lat1, lng1, lat2, lng2):
    """Planner distance in km: measured road km when a RoadMatrix is active and knows the pair, else
    straight-line x circuity (legacy name kept; 1.0 = pure haversine)."""
    m = _ROAD_MATRIX.get()
    if m is None:
        return ROAD_CIRCUITY * crow_km(lat1, lng1, lat2, lng2)
    d = m.get(lat1, lng1, lat2, lng2)
    return d if d is not None else m.ratio * crow_km(lat1, lng1, lat2, lng2)


# Spoilage model parameters. Uncalibrated assumptions (see ALGORITHM_AND_RESULTS_V2.md section 23): a per-crop linear
# loss rate per hour, tripled for refrigeration-needing crops in an unrefrigerated vehicle, capped at 60%.
SPOIL_UNREFRIG_MULT = 3.0
SPOIL_CAP = 0.6


@contextlib.contextmanager
def spoilage_params(rate_scale=1.0, unrefrig_mult=None, cap=None):
    """Temporarily change the spoilage model: every crop's hourly rate x rate_scale, the unrefrigerated multiplier,
    and the loss cap. Used for sensitivity tests; restores everything on exit."""
    global SPOIL_UNREFRIG_MULT, SPOIL_CAP
    saved = (SPOIL_UNREFRIG_MULT, SPOIL_CAP, {c: v["base_spoil_per_hr"] for c, v in CROPS.items()})
    try:
        for v in CROPS.values():
            v["base_spoil_per_hr"] *= rate_scale
        if unrefrig_mult is not None:
            SPOIL_UNREFRIG_MULT = float(unrefrig_mult)
        if cap is not None:
            SPOIL_CAP = float(cap)
        yield
    finally:
        SPOIL_UNREFRIG_MULT, SPOIL_CAP = saved[0], saved[1]
        for c, r in saved[2].items():
            CROPS[c]["base_spoil_per_hr"] = r


def spoilage_fraction(crop, vehicle_refrigerated, transit_hours):
    info = CROPS[crop]
    rate = info["base_spoil_per_hr"]
    if info["needs_refrigeration"] and not vehicle_refrigerated:
        rate *= SPOIL_UNREFRIG_MULT
    return min(rate * transit_hours, SPOIL_CAP)


def spoilage_fraction_from_temp(crop, observed_temp_c, transit_hours):
    """Sensor-driven counterpart to spoilage_fraction(): the base pipeline
    only ever knows a vehicle's refrigerated/not design fact (a binary);
    a real sensor gives a continuous temperature. Spoilage rate increases
    linearly with how far observed_temp_c sits above a per-crop safe
    transit threshold (4C for crops needing refrigeration, 20C otherwise),
    +8%/C above that, capped at the same 0.6 loss ceiling as the rest of
    the model. Explicitly-not-fit assumption, same caveat as the rest of
    this prototype's spoilage modeling."""
    info = CROPS[crop]
    rate = info["base_spoil_per_hr"]
    threshold_c = 4.0 if info["needs_refrigeration"] else 20.0
    excess_c = max(0.0, observed_temp_c - threshold_c)
    rate *= (1.0 + 0.08 * excess_c)
    return min(rate * transit_hours, SPOIL_CAP)


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


# Type-mix weights shared by both fleet-sizing functions below (kept as
# one constant so the depot-aware version can't silently drift out of
# sync with the flat one it's meant to supersede as the default).
_FLEET_TYPE_WEIGHTS = {"mini_pickup": 0.10, "van": 0.20, "reefer_van": 0.10,
                       "truck_2t": 0.25, "reefer_2t": 0.15, "truck_5t": 0.13, "reefer_5t": 0.07}


def default_fleet_composition(n_farmers):
    """Scales a plausible fleet with TOTAL farmer count -- roughly 1
    vehicle per 40 farmers, split across types, skewed toward mid-size
    trucks. This is a judgment call for the POC, not a measured ratio.

    Superseded as generate_scenario_v2's default by
    depot_aware_fleet_composition() below -- this flat version sizes
    the whole fleet off n_farmers alone, blind to how those farmers are
    distributed in space. Kept for callers that only have a count, not
    farmer positions (e.g. quick what-if sizing)."""
    n_vehicles = max(4, round(n_farmers / 40))
    comp = {name: max(0, round(n_vehicles * w)) for name, w in _FLEET_TYPE_WEIGHTS.items()}
    if sum(comp.values()) == 0:
        comp["van"] = 1
    return comp


# Depot partition -- moved here (from algorithms_v2.py, unchanged logic)
# so fleet composition can be sized per-depot instead of off a single
# global farmer count. algorithms_v2.py imports these back for its own
# clustering step, so both stay on the exact same partition.
#
# FARMERS_PER_DEPOT is tied to the fleet-sizing ratio (~1 vehicle per 40
# farmers) so a depot's expected demand is roughly one vehicle-load's
# worth -- a reasoned default, not a fitted one.
FARMERS_PER_DEPOT = 40

# Fixed-size grid partition -- fallback only, for when sklearn isn't
# available (KMeans needs it). 2.2x the clustering eps_km used in
# algorithms_v2.py (EPS_KM=12.0); kept as a literal here (rather than
# importing algorithms_v2, which would be circular) since it only
# matters for the no-sklearn fallback path.
DEPOT_CELL_KM = 26.4

# Reference per-depot bounding-box area for _spread_based_depot_floor()
# below -- empirically ~2,880 km^2/depot at n=300-10,000 in this
# module's own generate_scenario_v2() scenarios (where farmer density
# is roughly constant by construction), i.e. what FARMERS_PER_DEPOT=40
# already implies spatially once n is past small-count rounding
# artifacts. NOT the same constant as DEPOT_CELL_KM (that one comes
# from the unrelated DBSCAN clustering radius and was never calibrated
# to agree with FARMERS_PER_DEPOT -- see _spread_based_depot_floor()'s
# docstring for what went wrong when an earlier version used it here).
DEPOT_REFERENCE_AREA_KM2 = 2880.0


def _grid_partition(farmer_list, cell_km=DEPOT_CELL_KM):
    if not farmer_list:
        return []
    cells = defaultdict(list)
    for f in farmer_list:
        lat_step = cell_km / 111.0
        lng_step = cell_km / max(1e-6, 111.0 * math.cos(math.radians(f.lat)))
        cells[(int(f.lat // lat_step), int(f.lng // lng_step))].append(f)
    return list(cells.values())


def _spread_based_depot_floor(farmer_list, reference_area_km2=DEPOT_REFERENCE_AREA_KM2):
    """Fix for the n<=100 regression traced in ALGORITHM_AND_RESULTS_V2.md
    s3/s6: farmer-count-based sizing alone (round(n/farmers_per_depot))
    can floor to 1 depot even when the farmers span a non-trivial area,
    because it has no notion of physical distance -- a spread-out n=50
    gets the exact same 1-depot treatment as a tightly-clustered n=50
    would.

    reference_area_km2 is the per-depot bounding-box area the
    count-based formula ITSELF already implies once farmer count is
    large enough to be past low-count rounding artifacts (empirically
    ~2,880 km^2/depot at n=300-10,000 in the benchmark's own synthetic
    scenarios, i.e. what FARMERS_PER_DEPOT=40 actually corresponds to
    spatially under that data's typical density). This floor only adds
    depots when a population's actual area is large relative to THAT
    reference for its own count-based depot number -- so a normally-
    proportioned population (small n, small area, matching the same
    density every larger scenario has) is untouched, and this doesn't
    become a second, uncalibrated depot-count formula that silently
    outranks the farmer-count one at every scale.

    An earlier version of this function tiled the whole bounding box
    with fixed DEPOT_CELL_KM-sized cells (the grid-partition fallback's
    cell size) and used the cell count directly as the floor. Caught
    before benchmarking: DEPOT_CELL_KM (derived from the DBSCAN
    clustering radius, EPS_KM) and FARMERS_PER_DEPOT (the fleet-sizing
    ratio) were never calibrated to agree, and in fact differ by a
    roughly constant ~4x factor in implied per-depot area at every
    scale (not just small n) -- so that version wasn't a spread-anomaly
    check at all, it silently forced ~4x more depots than the
    count-based formula EVERYWHERE, including the n=300-10,000 range
    already validated in prior rounds. Confirmed by testing: it
    produced 1,054 depots (~3-9 farmers each) at n=10,000 vs. the
    validated 250, which would also have wrecked
    depot_aware_fleet_composition()'s per-depot vehicle-equivalent sum
    (each of those 1,054 tiny depots floors to its own vehicle).
    """
    if len(farmer_list) <= 1:
        return 1
    lats = [f.lat for f in farmer_list]
    lngs = [f.lng for f in farmer_list]
    mean_lat = sum(lats) / len(lats)
    lat_span_km = (max(lats) - min(lats)) * 111.0
    lng_span_km = (max(lngs) - min(lngs)) * 111.0 * max(1e-6, math.cos(math.radians(mean_lat)))
    area_km2 = lat_span_km * lng_span_km
    return max(1, round(area_km2 / reference_area_km2))


def _depot_partition(farmer_list, farmers_per_depot=FARMERS_PER_DEPOT):
    n = len(farmer_list)
    if n <= 1:
        return [farmer_list]
    n_depots = max(1, round(n / farmers_per_depot))
    # Take the max of the count-based figure and the spread-based floor
    # (not swapping one count-only heuristic for another, per the
    # ALGORITHM_AND_RESULTS_V2.md s6 next-step note) -- whichever calls
    # for more depots wins; a low-n, wide-spread population no longer
    # collapses to a single depot just because round(n/40)==1.
    n_depots = max(n_depots, _spread_based_depot_floor(farmer_list))
    n_depots = min(n_depots, n)  # can't ask KMeans for more clusters than points
    if not _HAVE_SKLEARN or n_depots >= n:
        return _grid_partition(farmer_list)  # fallback: no sklearn, or too few farmers to cluster
    coords = np.array([[f.lat, f.lng] for f in farmer_list])
    labels = KMeans(n_clusters=n_depots, n_init=4, random_state=0).fit(coords).labels_
    groups = defaultdict(list)
    for f, lab in zip(farmer_list, labels):
        groups[lab].append(f)
    return list(groups.values())


def depot_aware_fleet_composition(farmers, farmers_per_depot=FARMERS_PER_DEPOT):
    """Fix for the confirmed coverage-plateau root cause (see
    ALGORITHM_AND_RESULTS_V2.md s6): default_fleet_composition() sized
    the WHOLE fleet off a single global farmer count, so two scenarios
    with the same n but different spatial spread (one dense clump vs.
    several separate pockets) got the identical fleet -- even though
    each independent pocket genuinely needs its own minimum service
    capacity; one pocket's vehicle can't be "shared" with a pocket
    hours away inside the same tight ready/deadline window.

    Partitions farmers the same way _depot_partition() does for
    clustering, sizes each depot's fleet independently off ITS OWN
    farmer count (same ~1-per-40 ratio and type-mix weights as the flat
    version, just applied per depot instead of once globally), then
    sums the per-depot compositions into the single fleet
    make_fleet() still expects.

    This directly "adds capacity where the density is": a population
    spread across several small pockets now gets a vehicle per pocket
    (each independently floored at >=1), rather than being smoothed
    into one global ratio that can undercount how many independent
    service pockets actually exist. A single dense population behaves
    the same as before (one depot, same math as the flat version).

    Vehicles are still a single shared, location-agnostic pool at
    assignment time (assign_fleet() in algorithms_v2.py isn't
    depot-bound) -- this fix targets fleet SIZE, not routing.
    Distributing vehicles to be depot-BOUND is a separate, larger
    change and is not what this function does.

    Important: this recomputes the TOTAL vehicle count (still applying
    the type-mix weights once, globally, exactly like the flat
    version) rather than re-deriving a separate type mix per depot.
    An earlier version of this function applied the ~1-per-40 formula
    a SECOND time within each depot -- but FARMERS_PER_DEPOT is the
    same constant depots are already sized around, so a typical
    depot's own farmer count divided by 40 rounds to ~1 almost every
    time, collapsing every depot's local type mix to a single
    fallback vehicle (observed in testing: 100% "van" fleets at
    n=1,000-10,000, a real regression, not just a style choice).
    Keeping the type-mix computation global and letting only the
    TOTAL vary with depot count avoids that collapse.
    """
    depots = _depot_partition(list(farmers), farmers_per_depot)
    # Each depot's demand contributes at least one full "vehicle
    # equivalent" toward the total, even if its own farmer count is
    # well under farmers_per_depot -- this is what actually captures
    # "many small, separate pockets need more total capacity than one
    # flat n/40 ratio assumes," without touching the type-mix step.
    # A single depot (or evenly-sized depots near farmers_per_depot)
    # reduces to ~n/farmers_per_depot, the same total the flat version
    # computed.
    vehicle_equivalents = sum(max(1.0, len(d) / farmers_per_depot) for d in depots)
    n_vehicles = max(4, round(vehicle_equivalents))
    comp = {name: max(0, round(n_vehicles * w)) for name, w in _FLEET_TYPE_WEIGHTS.items()}
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
        fleet_composition = depot_aware_fleet_composition(farmers)
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
        if crop not in m.capacity_kg or crop not in m.price:
            continue  # this market doesn't quote `crop` at all -- not a demand node for it
        cap = m.capacity_kg[crop]
        price = m.price[crop]
        if hasattr(elastic_pricing, "tranche_nodes"):       # a price_impact.PriceImpact: data-driven tranches
            nodes.extend(elastic_pricing.tranche_nodes(m, crop))
        elif not elastic_pricing:
            nodes.append({"market": m, "capacity_kg": cap, "price": price})
        else:
            for share, mult in zip(tranche_shares, tranche_price_mult):
                nodes.append({"market": m, "capacity_kg": cap * share, "price": price * mult})
    return nodes


def fresh_capacity(markets):
    return {m.id: dict(m.capacity_kg) for m in markets}
