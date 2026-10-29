"""
roads.py
--------
Real-road geometry for planned routes. DISPLAY LAYER ONLY.

The optimizer still plans with its own distance/time model (haversine x road
circuity, AVG_SPEED_KMPH). This module never feeds back into it. It takes the
stop sequence of an already-computed route, asks a routing service for the
road path through those stops (OpenStreetMap data), and stores the result in
the `road_routes` table so each route is fetched from the provider only once.

Providers (pick with ROUTING_PROVIDER; default = "ors" if ORS_API_KEY is set,
else "osrm"):
  ors   openrouteservice.org  -- free key, ~2,000 directions/day, 40/min.
  osrm  router.project-osrm.org demo server -- no key, ~1 request/s,
        non-commercial, no uptime guarantee. Fine for development / a demo.
        Set OSRM_BASE_URL to point at your own OSRM instead.
  off   disable (routes stay straight lines).

Other env vars: ORS_API_KEY, ROUTING_PROFILE (ors: driving-car | driving-hgv;
osrm: driving), ROUTING_USER_AGENT.

PLANNING DISTANCES (second half of this file). The optimizer can plan on measured road distances: for every
farmer/market pair it asks an OSRM-compatible `table` service for the road km (cached in `road_matrices`),
and logistics_lib_v2.use_road_matrix() makes every planner distance follow it. Each plan stores which model it
used (`distance_model`), so the map later replays exactly the distances the optimizer saw. Env: ROAD_PLANNING=off
disables it; ROAD_MATRIX_MAX_POINTS (default 200) caps the matrix size (bigger scenarios use a road factor measured
on a sample instead); OSRM_BASE_URL points at your own OSRM. (The matrix always uses OSRM `table`, because
openrouteservice's matrix refuses points more than 350 m from a road, which rural farm coordinates often are.)

Honesty rules:
  - Only road DISTANCE and GEOMETRY are used. Provider travel times are ignored:
    OpenStreetMap speed tags are patchy in India, so engine durations are not
    trustworthy; the plan's own timing model stays in charge of the clock.
  - Farmer/market coordinates are rarely exactly on a road. Each leg starts and
    ends at the exact stop coordinate, with a short straight connector to the
    nearest road point; its length is reported as `offRoadKm`.
  - A route is only labelled geometry="road" when road data for it was found.
"""

import contextlib
import datetime
import hashlib
import json
import logging
import math
import os
import random
import statistics
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

from logistics_lib_v2 import RoadMatrix, crow_km, get_road_circuity, road_circuity, use_road_matrix

log = logging.getLogger(__name__)

ORS_URL = "https://api.openrouteservice.org/v2/directions/{profile}/geojson"
OSRM_DEFAULT_BASE = "https://router.project-osrm.org"

# Seconds between outgoing calls, per provider (stay under the free limits).
_MIN_INTERVAL = {"ors": 1.6, "osrm": 1.1}
_RETRY_STATUS = {429, 502, 503, 504}
_NEG_CACHE_SECONDS = 600
SIMPLIFY_TOLERANCE_M = 5.0


class RoutingError(Exception):
    pass


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def provider_name() -> Optional[str]:
    p = os.environ.get("ROUTING_PROVIDER", "").strip().lower()
    if p in ("off", "none", "disabled", "false", "0"):
        return None
    if p in ("ors", "osrm"):
        return p
    return "ors" if os.environ.get("ORS_API_KEY") else "osrm"


def profile_name(provider: Optional[str] = None) -> str:
    provider = provider or provider_name()
    env = os.environ.get("ROUTING_PROFILE", "").strip()
    if env:
        return env
    return "driving-car" if provider == "ors" else "driving"


def _user_agent() -> str:
    return os.environ.get("ROUTING_USER_AGENT", "farmroute-optimizer/1.0 (student project)")


# ---------------------------------------------------------------------------
# geometry helpers (pure)
# ---------------------------------------------------------------------------

def _km(a: Sequence[float], b: Sequence[float]) -> float:
    """Pure great-circle km between two [lng, lat] points (crow_km, NOT the planner's circuity-scaled haversine)."""
    return crow_km(a[1], a[0], b[1], b[0])


def simplify(path: List[List[float]], tolerance_m: float = SIMPLIFY_TOLERANCE_M) -> List[List[float]]:
    """Ramer-Douglas-Peucker on [lng, lat] points. Keeps both endpoints."""
    n = len(path)
    if n <= 2:
        return path[:]
    lat0 = math.radians(sum(p[1] for p in path) / n)
    kx, ky = 111_320.0 * math.cos(lat0), 110_540.0
    xy = [(p[0] * kx, p[1] * ky) for p in path]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        seg2 = dx * dx + dy * dy
        best, best_d = -1, -1.0
        for k in range(i + 1, j):
            px, py = xy[k]
            if seg2 == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                u = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg2))
                d = math.hypot(px - (x1 + u * dx), py - (y1 + u * dy))
            if d > best_d:
                best, best_d = k, d
        if best_d > tolerance_m:
            keep[best] = True
            stack.append((i, best))
            stack.append((best, j))
    return [p for p, k in zip(path, keep) if k]


def _dedupe(path: List[List[float]]) -> List[List[float]]:
    out: List[List[float]] = []
    for p in path:
        q = [round(p[0], 5), round(p[1], 5)]
        if not out or out[-1] != q:
            out.append(q)
    return out


def assemble_legs(stops: List[dict], coords: List[List[float]], way_points: List[int],
                  leg_distance_m: List[float], tolerance_m: float = SIMPLIFY_TOLERANCE_M) -> List[dict]:
    """Provider output -> one entry per consecutive stop pair:
    {coordinates: [[lng, lat], ...], distanceKm, offRoadKm}. Each leg starts/ends at the EXACT stop coordinates."""
    n = len(stops)
    if n < 2:
        raise RoutingError("need at least two stops")
    if len(way_points) != n or len(leg_distance_m) != n - 1:
        raise RoutingError("routing response does not match the requested stops")
    if any(b < a for a, b in zip(way_points, way_points[1:])) or way_points[-1] >= len(coords):
        raise RoutingError("routing response has inconsistent waypoint indices")
    legs = []
    for k in range(n - 1):
        seg = [list(c[:2]) for c in coords[way_points[k]: way_points[k + 1] + 1]]
        if not seg:
            seg = [list(coords[way_points[k]][:2])]
        a = [stops[k]["lng"], stops[k]["lat"]]
        b = [stops[k + 1]["lng"], stops[k + 1]["lat"]]
        off_km = _km(a, seg[0]) + _km(seg[-1], b)
        path = _dedupe(simplify([a] + seg + [b], tolerance_m))
        if len(path) < 2:                       # two stops at the same spot
            path = [[round(a[0], 5), round(a[1], 5)], [round(b[0], 5), round(b[1], 5)]]
        legs.append({
            "coordinates": path,
            "distanceKm": round(leg_distance_m[k] / 1000.0 + off_km, 3),
            "offRoadKm": round(off_km, 3),
        })
    return legs


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------

_throttle_lock = threading.Lock()
_last_call = 0.0


def _throttle(provider: str) -> None:
    global _last_call
    with _throttle_lock:
        wait = _MIN_INTERVAL.get(provider, 1.0) - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _http_json(method: str, url: str, provider: str, **kwargs) -> dict:
    headers = {"User-Agent": _user_agent(), **kwargs.pop("headers", {})}
    last = ""
    for attempt in range(2):
        _throttle(provider)
        try:
            res = httpx.request(method, url, headers=headers, timeout=25.0, **kwargs)
        except httpx.HTTPError as e:
            raise RoutingError(f"could not reach {provider}: {e}") from e
        if res.status_code in _RETRY_STATUS and attempt == 0:
            last = f"HTTP {res.status_code}"
            time.sleep(2.0)
            continue
        if res.status_code == 429:
            raise RoutingError(f"{provider} rate limit / daily quota reached (HTTP 429)")
        if res.status_code >= 400:
            try:
                detail = res.json()
            except ValueError:
                detail = res.text[:200]
            raise RoutingError(f"{provider} HTTP {res.status_code}: {str(detail)[:300]}")
        try:
            return res.json()
        except ValueError as e:
            raise RoutingError(f"{provider} returned non-JSON ({last or 'ok'})") from e
    raise RoutingError(f"{provider} unavailable ({last})")


def parse_osrm(data: dict) -> Tuple[List[List[float]], List[int], List[float]]:
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(f"osrm: {data.get('code')} {data.get('message', '')}".strip())
    coords: List[List[float]] = []
    way_points = [0]
    dists: List[float] = []
    for leg in data["routes"][0]["legs"]:
        for step in leg.get("steps", []):
            pts = step["geometry"]["coordinates"]
            if coords and pts and coords[-1][:2] == pts[0][:2]:
                pts = pts[1:]
            coords.extend([p[:2] for p in pts])
        if not coords:
            raise RoutingError("osrm: empty geometry")
        way_points.append(len(coords) - 1)
        dists.append(float(leg["distance"]))
    return coords, way_points, dists


def parse_ors(data: dict) -> Tuple[List[List[float]], List[int], List[float]]:
    feats = data.get("features") or []
    if not feats:
        raise RoutingError("ors: no route in response")
    props = feats[0]["properties"]
    coords = [c[:2] for c in feats[0]["geometry"]["coordinates"]]
    way_points = [int(i) for i in props["way_points"]]
    dists = [float(s["distance"]) for s in props["segments"]]
    return coords, way_points, dists


def _fetch_osrm(stops: List[dict], profile: str):
    base = os.environ.get("OSRM_BASE_URL", OSRM_DEFAULT_BASE).rstrip("/")
    path = ";".join(f"{s['lng']:.6f},{s['lat']:.6f}" for s in stops)
    data = _http_json("GET", f"{base}/route/v1/{profile}/{path}", "osrm",
                      params={"overview": "false", "geometries": "geojson", "steps": "true"})
    return parse_osrm(data)


def _fetch_ors(stops: List[dict], profile: str):
    key = os.environ.get("ORS_API_KEY")
    if not key:
        raise RoutingError("ORS_API_KEY is not set")
    body = {"coordinates": [[s["lng"], s["lat"]] for s in stops],
            "radiuses": [-1] * len(stops), "instructions": False}
    data = _http_json("POST", ORS_URL.format(profile=profile), "ors", json=body,
                      headers={"Authorization": key, "Content-Type": "application/json"})
    return parse_ors(data)


def fetch_route(provider: str, profile: str, stops: List[dict]) -> List[dict]:
    fetch = _fetch_ors if provider == "ors" else _fetch_osrm
    coords, way_points, dists = fetch(stops, profile)
    return assemble_legs(stops, coords, way_points, dists)


# ---------------------------------------------------------------------------
# cache (Postgres table road_routes)
# ---------------------------------------------------------------------------

def route_key(provider: str, profile: str, stops: List[dict]) -> str:
    s = provider + "|" + profile + "|" + ";".join(f"{st['lat']:.5f},{st['lng']:.5f}" for st in stops)
    return hashlib.sha1(s.encode()).hexdigest()


def load_cached(conn, keys) -> Dict[str, List[dict]]:
    keys = list(keys)
    if not keys:
        return {}
    rows = conn.execute("SELECT key, legs FROM road_routes WHERE key = ANY(%s)", (keys,)).fetchall()
    return {r["key"]: json.loads(r["legs"]) for r in rows}


def store(conn, key: str, provider: str, profile: str, legs: List[dict]) -> None:
    conn.execute(
        "INSERT INTO road_routes (key, provider, profile, legs, created_at) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (key) DO NOTHING",
        (key, provider, profile, json.dumps(legs, separators=(",", ":")),
         datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()


_failed: Dict[str, Tuple[float, str]] = {}   # key -> (retry_after_monotonic, message)


# ---------------------------------------------------------------------------
# plan-level helpers used by main.py
# ---------------------------------------------------------------------------

def _routable(solution: dict):
    for r in solution.get("routes", []):
        if len(r.get("stops", [])) >= 2:
            yield r


def _apply(route: dict, legs: List[dict], provider: str) -> None:
    coords: List[List[float]] = []
    for i, leg in enumerate(legs):
        coords.extend(leg["coordinates"] if i == 0 else leg["coordinates"][1:])
    route["roadLegs"] = legs
    route["roadCoordinates"] = coords
    route["roadDistanceKm"] = round(sum(l["distanceKm"] for l in legs), 2)
    route["roadOffRoadKm"] = round(sum(l["offRoadKm"] for l in legs), 2)
    route["roadProvider"] = provider
    route["geometry"] = "road"


def attach_cached(conn, payload: dict) -> None:
    """Adds road geometry to every route that already has it cached, plus a top-level
    `roads` block telling the frontend how many routes per algorithm are still pending."""
    provider = provider_name()
    info = {"enabled": provider is not None, "provider": provider,
            "profile": profile_name(provider) if provider else None, "pending": {}}
    payload["roads"] = info
    if provider is None:
        return
    profile = info["profile"]
    keyed = []
    for algo, sol in payload["solutions"].items():
        for r in _routable(sol):
            keyed.append((algo, r, route_key(provider, profile, r["stops"])))
    cached = load_cached(conn, {k for _, _, k in keyed})
    pending: Dict[str, set] = {a: set() for a in payload["solutions"]}
    for algo, r, key in keyed:
        legs = cached.get(key)
        if legs and len(legs) == len(r["stops"]) - 1:
            _apply(r, legs, provider)
        else:
            pending[algo].add(key)
    info["pending"] = {a: len(s) for a, s in pending.items()}


def resolve_pending(conn, solution: dict, budget_s: float = 15.0) -> dict:
    """Fetches (and caches) road geometry for this algorithm's uncached routes,
    stopping once `budget_s` seconds are used. Call repeatedly until pending == 0."""
    provider = provider_name()
    if provider is None:
        return {"enabled": False, "provider": None, "total": 0, "pending": 0, "resolved": 0, "failed": 0, "error": None}
    profile = profile_name(provider)
    unique: Dict[str, List[dict]] = {}
    for r in _routable(solution):
        unique.setdefault(route_key(provider, profile, r["stops"]), r["stops"])
    cached = load_cached(conn, unique.keys())
    start = time.monotonic()
    resolved = failed = 0
    error = None
    for key, stops in unique.items():
        if key in cached:
            continue
        if time.monotonic() - start > budget_s:
            break
        blocked = _failed.get(key)
        if blocked and blocked[0] > time.monotonic():
            failed += 1
            error = error or blocked[1]
            continue
        try:
            legs = fetch_route(provider, profile, stops)
        except RoutingError as e:
            _failed[key] = (time.monotonic() + _NEG_CACHE_SECONDS, str(e))
            failed += 1
            error = str(e)
            continue
        store(conn, key, provider, profile, legs)
        cached[key] = legs
        resolved += 1
    return {"enabled": True, "provider": provider, "total": len(unique), "pending": len(unique) - len(cached),
            "resolved": resolved, "failed": failed, "error": error}


# ---------------------------------------------------------------------------
# `python roads.py` : one-off check that your provider/key work (no database needed)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    prov = provider_name()
    print(f"provider={prov} profile={profile_name(prov) if prov else None}")
    if prov is None:
        raise SystemExit("ROUTING_PROVIDER is off")
    # Patna Junction -> Gandhi Maidan: a short, well-mapped urban leg.
    test = [{"lat": 25.6093, "lng": 85.1376}, {"lat": 25.6200, "lng": 85.1470}]
    legs = fetch_route(prov, profile_name(prov), test)
    straight = _km([test[0]["lng"], test[0]["lat"]], [test[1]["lng"], test[1]["lat"]])
    leg = legs[0]
    print(f"OK  road {leg['distanceKm']} km vs straight {straight:.2f} km "
          f"(ratio {leg['distanceKm'] / straight:.2f}), {len(leg['coordinates'])} points, "
          f"off-road connectors {leg['offRoadKm']} km")


# ===========================================================================
# Planning distances: road-km matrix between every farmer and market
# ===========================================================================

MATRIX_BLOCK = 50                 # OSRM caps a table request at 100 locations -> 50 sources x 50 destinations
SAMPLE_POINTS = 40


def matrix_enabled() -> bool:
    return os.environ.get("ROAD_PLANNING", "auto").strip().lower() not in ("off", "none", "false", "0") \
        and provider_name() is not None


def matrix_max_points() -> int:
    try:
        return max(2, int(os.environ.get("ROAD_MATRIX_MAX_POINTS", "200")))
    except ValueError:
        return 200


def _round_pt(lat: float, lng: float) -> Tuple[float, float]:
    return (round(float(lat), 6), round(float(lng), 6))


def canonical_points(points) -> List[Tuple[float, float]]:
    """Unique points (rounded to 6 dp ~ 0.1 m), sorted -> a stable order for the cache key and matrix rows."""
    return sorted({_round_pt(la, ln) for la, ln in points})


def matrix_key(provider: str, profile: str, uniq: List[Tuple[float, float]]) -> str:
    s = provider + "|" + profile + "|" + ";".join(f"{la:.6f},{ln:.6f}" for la, ln in uniq)
    return hashlib.sha1(s.encode()).hexdigest()


def parse_table(data: dict, n_src: int, n_dst: int):
    """OSRM table response -> (metres matrix with None for unroutable, source snap m, destination snap m)."""
    if data.get("code") != "Ok" or "distances" not in data:
        raise RoutingError(f"osrm table: {data.get('code')} {data.get('message', '')}".strip())
    dist = data["distances"]
    if len(dist) != n_src or any(len(r) != n_dst for r in dist):
        raise RoutingError("osrm table: response size does not match the request")
    src = [float(w.get("distance") or 0.0) for w in data.get("sources", [])] or [0.0] * n_src
    dst = [float(w.get("distance") or 0.0) for w in data.get("destinations", [])] or [0.0] * n_dst
    return dist, src, dst


def _fetch_table(profile: str, src_pts, dst_pts, same: bool):
    base = os.environ.get("OSRM_BASE_URL", OSRM_DEFAULT_BASE).rstrip("/")
    pts = list(src_pts) if same else list(src_pts) + list(dst_pts)
    coords = ";".join(f"{ln:.6f},{la:.6f}" for la, ln in pts)
    url = f"{base}/table/v1/{profile}/{coords}?annotations=distance"
    if not same:
        n = len(src_pts)
        url += "&sources=" + ";".join(str(i) for i in range(n))
        url += "&destinations=" + ";".join(str(n + j) for j in range(len(dst_pts)))
    return parse_table(_http_json("GET", url, "osrm"), len(src_pts), len(dst_pts))


def build_matrix_km(uniq: List[Tuple[float, float]], profile: str, fetch=_fetch_table) -> List[List[Optional[float]]]:
    """Road km for every ordered pair of `uniq`. Each cell = OSRM road distance + the straight connector from each
    point to its nearest road (the vehicle really has to cover it) and never less than the straight-line distance.
    None where OSRM found no route."""
    n = len(uniq)
    raw: List[List[Optional[float]]] = [[None] * n for _ in range(n)]
    snap = [0.0] * n
    blocks = [(i, min(i + MATRIX_BLOCK, n)) for i in range(0, n, MATRIX_BLOCK)]
    for (a0, a1) in blocks:
        for (b0, b1) in blocks:
            same = n <= MATRIX_BLOCK
            dist, s_snap, d_snap = fetch(profile, uniq[a0:a1], uniq[b0:b1], same)
            for i in range(a1 - a0):
                snap[a0 + i] = s_snap[i]
                for j in range(b1 - b0):
                    raw[a0 + i][b0 + j] = dist[i][j]
            for j in range(b1 - b0):
                snap[b0 + j] = d_snap[j]
    km: List[List[Optional[float]]] = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                km[i][j] = 0.0
            elif raw[i][j] is not None:
                straight = crow_km(uniq[i][0], uniq[i][1], uniq[j][0], uniq[j][1])
                km[i][j] = round(max(straight, raw[i][j] / 1000.0 + (snap[i] + snap[j]) / 1000.0), 4)
    return km


def matrix_ratio(uniq, km) -> float:
    """Median road/straight over pairs more than 1 km apart (short pairs are dominated by snapping), clipped to
    the planner's valid [1, 3]; 1.0 when there is nothing to measure."""
    r = []
    for i in range(len(uniq)):
        for j in range(len(uniq)):
            if i != j and km[i][j] is not None:
                st = crow_km(uniq[i][0], uniq[i][1], uniq[j][0], uniq[j][1])
                if st >= 1.0:
                    r.append(km[i][j] / st)
    return min(3.0, max(1.0, statistics.median(r))) if r else 1.0


def load_matrix_row(conn, key: str):
    row = conn.execute("SELECT points, dist, ratio FROM road_matrices WHERE key = %s", (key,)).fetchone()
    return None if row is None else (json.loads(row["points"]), json.loads(row["dist"]), float(row["ratio"]))


def store_matrix(conn, key: str, provider: str, profile: str, uniq, km, ratio: float) -> None:
    conn.execute(
        "INSERT INTO road_matrices (key, provider, profile, points, dist, ratio, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING",
        (key, provider, profile, json.dumps([list(p) for p in uniq], separators=(",", ":")),
         json.dumps(km, separators=(",", ":")), ratio, datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()


def _to_road_matrix(exact_points, uniq, km, ratio) -> RoadMatrix:
    row_of = {tuple(p): i for i, p in enumerate(uniq)}
    index = {}
    for la, ln in exact_points:
        i = row_of.get(_round_pt(la, ln))
        if i is not None:
            index[(la, ln)] = i
    return RoadMatrix(index, km, ratio)


def plan_distance_model(conn, farmers, markets, enabled: bool = True):
    """Decide how this plan measures distance. Returns (model, RoadMatrix or None). `model` is JSON stored with the
    plan: {type: road_matrix | circuity | straight, ...}. Never raises: if road data is unavailable the plan is
    computed on straight lines (or the configured circuity) exactly as before, and `note` says why."""
    k = get_road_circuity()
    fallback = {"type": "straight", "k": k} if k == 1.0 else {"type": "circuity", "k": k, "source": "env"}
    if not enabled:
        return {**fallback, "note": "road distances switched off for this plan"}, None
    if not matrix_enabled():
        return fallback, None
    exact = [(f.lat, f.lng) for f in farmers] + [(m.lat, m.lng) for m in markets]
    uniq = canonical_points(exact)
    if len(uniq) < 2:
        return fallback, None
    provider, profile = "osrm", profile_name("osrm")
    try:
        if len(uniq) > matrix_max_points():
            rng = random.Random(7)
            sample = sorted(rng.sample(uniq, min(SAMPLE_POINTS, len(uniq))))
            ratio = matrix_ratio(sample, build_matrix_km(sample, profile))
            return {"type": "circuity", "k": round(ratio, 3), "source": "road_sample", "provider": provider,
                    "n_points": len(uniq), "sample_points": len(sample),
                    "note": f"{len(uniq)} points is more than ROAD_MATRIX_MAX_POINTS; road factor measured on a "
                            f"{len(sample)}-point sample"}, None
        key = matrix_key(provider, profile, uniq)
        cached = load_matrix_row(conn, key)
        if cached is None:
            km = build_matrix_km(uniq, profile)
            ratio = matrix_ratio(uniq, km)
            store_matrix(conn, key, provider, profile, uniq, km, ratio)
        else:
            _pts, km, ratio = cached
        model = {"type": "road_matrix", "provider": provider, "profile": profile, "key": key,
                 "n_points": len(uniq), "ratio": round(ratio, 3)}
        return model, _to_road_matrix(exact, uniq, km, ratio)
    except Exception as e:  # roads are an enhancement: never let them break plan computation
        log.warning("road distances unavailable, planning on straight lines: %s", e)
        return {**fallback, "note": f"road distances unavailable ({e})"}, None


@contextlib.contextmanager
def distance_context(conn, snapshot: dict):
    """Re-create the distance model a stored plan was computed with, so anything derived from it later (the map's
    timeline, distances) uses exactly the distances the optimizer saw. Plans without a stored model behave as before."""
    model = snapshot.get("distance_model") or {}
    with contextlib.ExitStack() as stack:
        if model.get("type") == "road_matrix":
            matrix = None
            cached = load_matrix_row(conn, model.get("key", ""))
            if cached is not None:
                uniq, km, ratio = cached
                exact = [(f["lat"], f["lng"]) for f in snapshot.get("farmers", [])] + \
                        [(m["lat"], m["lng"]) for m in snapshot.get("markets", [])]
                matrix = _to_road_matrix(exact, [tuple(p) for p in uniq], km, ratio)
            if matrix is not None:
                stack.enter_context(use_road_matrix(matrix))
            else:
                log.warning("road matrix %s missing from cache; replaying with its measured ratio", model.get("key"))
                stack.enter_context(road_circuity(float(model.get("ratio", 1.0))))
        elif model.get("type") == "circuity":
            stack.enter_context(road_circuity(float(model["k"])))
        yield
