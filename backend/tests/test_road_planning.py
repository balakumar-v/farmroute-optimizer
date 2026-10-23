"""Tests for planning on measured road distances (RoadMatrix hook, matrix building, model persistence). No network/DB."""
import json
import threading

import numpy as np
import pytest

import logistics_lib_v2 as lib
import roads
from logistics_lib_v2 import Farmer, Market, RoadMatrix, crow_km, haversine, use_road_matrix

P = [(25.0, 84.0), (25.0, 84.2), (25.2, 84.2)]


def _matrix(scale=2.0, ratio=1.4):
    km = [[0.0 if i == j else scale * crow_km(*P[i], *P[j]) for j in range(3)] for i in range(3)]
    return RoadMatrix({p: i for i, p in enumerate(P)}, km, ratio), km


# ---- the hook in logistics_lib_v2 ----

def test_haversine_uses_matrix_inside_context_only():
    m, km = _matrix()
    straight = haversine(*P[0], *P[1])
    with use_road_matrix(m):
        assert haversine(*P[0], *P[1]) == pytest.approx(km[0][1])
        assert haversine(*P[0], *P[1]) == pytest.approx(2.0 * straight)
        assert haversine(*P[1], *P[0]) == pytest.approx(km[1][0])        # directed lookup
        assert haversine(*P[0], *P[0]) == 0.0
    assert haversine(*P[0], *P[1]) == pytest.approx(straight)             # restored


def test_unknown_pair_falls_back_to_matrix_ratio_and_ratio_drives_circuity():
    m, _ = _matrix(ratio=1.4)
    far = (26.0, 85.0)
    with use_road_matrix(m):
        assert lib.get_road_circuity() == pytest.approx(1.4)
        assert haversine(*P[0], *far) == pytest.approx(1.4 * crow_km(*P[0], *far))
    assert lib.get_road_circuity() == lib.ROAD_CIRCUITY


def test_numpy_scalars_hit_the_same_keys():
    m, km = _matrix()
    lat = np.array([p[0] for p in P]); lng = np.array([p[1] for p in P])
    with use_road_matrix(m):
        assert haversine(lat[0], lng[0], lat[1], lng[1]) == pytest.approx(km[0][1])


def test_override_vec_replaces_known_pairs_only():
    m, km = _matrix()
    lat = np.array([P[0][0], P[1][0], 30.0]); lng = np.array([P[0][1], P[1][1], 90.0])
    base = np.full(3, 111.0)
    with use_road_matrix(m):
        out = m.override_vec(base, lat, lng, P[2][0], P[2][1])            # scalar destination broadcast
    assert out[0] == pytest.approx(km[0][2]) and out[1] == pytest.approx(km[1][2])
    assert out[2] == 111.0                                                # unknown point keeps the fallback


def test_vectorized_ilo_distance_follows_the_matrix():
    import ilo_v3
    m, km = _matrix()
    lat = np.array([P[0][0], P[1][0]]); lng = np.array([P[0][1], P[1][1]])
    with use_road_matrix(m):
        d = ilo_v3._vec_haversine(lat, lng, P[2][0], P[2][1])
    assert d[0] == pytest.approx(km[0][2]) and d[1] == pytest.approx(km[1][2])
    d0 = ilo_v3._vec_haversine(lat, lng, P[2][0], P[2][1])               # outside: plain straight-line
    assert d0[0] == pytest.approx(crow_km(P[0][0], P[0][1], P[2][0], P[2][1]) * lib.ROAD_CIRCUITY)


def test_matrix_is_invisible_to_other_threads():
    m, _ = _matrix()
    seen = {}
    with use_road_matrix(m):
        t = threading.Thread(target=lambda: seen.update(m=lib.get_road_matrix()))
        t.start(); t.join()
    assert seen["m"] is None


# ---- building the matrix ----

def _fake_fetch(calls):
    """Pretend OSRM: road metres = 1.5 x straight, every point 100 m from its road."""
    def fetch(profile, src, dst, same):
        calls.append((len(src), len(dst), same))
        dist = [[1500.0 * crow_km(*a, *b) for b in dst] for a in src]
        return dist, [100.0] * len(src), [100.0] * len(dst)
    return fetch


def test_build_matrix_adds_snap_distance_and_never_beats_straight_line():
    uniq = roads.canonical_points(P)
    km = roads.build_matrix_km(uniq, "driving", fetch=_fake_fetch([]))
    for i in range(3):
        assert km[i][i] == 0.0
        for j in range(3):
            if i != j:
                straight = crow_km(*uniq[i], *uniq[j])
                assert km[i][j] == pytest.approx(1.5 * straight + 0.2, abs=1e-3)
                assert km[i][j] >= straight


def test_build_matrix_chunks_large_scenarios_and_fills_every_cell():
    pts = [(25.0 + 0.01 * i, 84.0 + 0.013 * i) for i in range(120)]
    uniq = roads.canonical_points(pts)
    calls = []
    km = roads.build_matrix_km(uniq, "driving", fetch=_fake_fetch(calls))
    assert len(calls) == 9 and all(s + d <= 100 for s, d, _ in calls)      # 3x3 blocks, each within OSRM's 100-location cap
    assert all(km[i][j] is not None for i in range(120) for j in range(120))
    assert km[3][97] == pytest.approx(1.5 * crow_km(*uniq[3], *uniq[97]) + 0.2, abs=1e-3)


def test_build_matrix_small_scenario_is_one_request():
    calls = []
    roads.build_matrix_km(roads.canonical_points(P), "driving", fetch=_fake_fetch(calls))
    assert calls == [(3, 3, True)]


def test_unroutable_pair_stays_unknown():
    def fetch(profile, src, dst, same):
        d = [[None if (a != b and a[1] > 84.1 and b[1] > 84.1) else 1000.0 for b in dst] for a in src]
        return d, [0.0] * len(src), [0.0] * len(dst)
    uniq = roads.canonical_points(P)
    km = roads.build_matrix_km(uniq, "driving", fetch=fetch)
    assert any(v is None for row in km for v in row)


def test_parse_table():
    ok = {"code": "Ok", "distances": [[0, 1200.5], [1300, 0]], "sources": [{"distance": 12}, {"distance": 40}],
          "destinations": [{"distance": 12}, {"distance": 40}]}
    d, s, t = roads.parse_table(ok, 2, 2)
    assert d[0][1] == 1200.5 and s == [12.0, 40.0]
    with pytest.raises(roads.RoutingError):
        roads.parse_table({"code": "TooBig"}, 2, 2)
    with pytest.raises(roads.RoutingError):
        roads.parse_table(ok, 3, 2)


def test_matrix_ratio_ignores_short_pairs_and_clips():
    uniq = roads.canonical_points([(25.0, 84.0), (25.0, 84.001), (25.0, 84.3)])
    km = [[0.0 if i == j else 10 * crow_km(*uniq[i], *uniq[j]) for j in range(3)] for i in range(3)]
    km[0][1] = km[1][0] = 0.5            # a 0.1 km pair with a silly ratio: must not drag the median
    assert roads.matrix_ratio(uniq, km) == pytest.approx(3.0)             # 10x clipped to the planner's max of 3
    assert roads.matrix_ratio(uniq[:1], [[0.0]]) == 1.0


# ---- choosing + persisting the model ----

class FakeConn:
    def __init__(self):
        self.matrices = {}
    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        outer = self
        class Cur:
            def fetchone(self_):
                if s.startswith("SELECT points, dist, ratio"):
                    return outer.matrices.get(params[0])
        if s.startswith("INSERT INTO road_matrices"):
            self.matrices.setdefault(params[0], {"points": params[3], "dist": params[4], "ratio": params[5]})
        return Cur()
    def commit(self):
        pass


FARMERS = [Farmer(id=i, lat=25.0 + 0.02 * i, lng=84.0 + 0.03 * i, crop="tomato", qty_kg=100, ready_hr=0, deadline_hr=48,
                  needs_refrigeration=False) for i in range(4)]
MARKETS = [Market(id=1, lat=25.3, lng=84.4, price={"tomato": 20}, capacity_kg={"tomato": 1000})]


@pytest.fixture
def osrm(monkeypatch):
    calls = []
    monkeypatch.setattr(roads, "_fetch_table", _fake_fetch(calls))
    monkeypatch.delenv("ROAD_PLANNING", raising=False)
    monkeypatch.delenv("ROUTING_PROVIDER", raising=False)
    monkeypatch.delenv("ROAD_MATRIX_MAX_POINTS", raising=False)
    # build_matrix_km binds fetch=_fetch_table at definition time, so route through the module attribute:
    real = roads.build_matrix_km
    monkeypatch.setattr(roads, "build_matrix_km", lambda u, p, fetch=None: real(u, p, fetch=roads._fetch_table))
    return calls


def test_model_is_road_matrix_and_second_plan_reuses_the_cache(osrm):
    conn = FakeConn()
    model, matrix = roads.plan_distance_model(conn, FARMERS, MARKETS)
    assert model["type"] == "road_matrix" and model["n_points"] == 5 and matrix is not None
    assert len(osrm) == 1 and len(conn.matrices) == 1
    d = matrix.get(FARMERS[0].lat, FARMERS[0].lng, MARKETS[0].lat, MARKETS[0].lng)
    assert d == pytest.approx(1.5 * crow_km(FARMERS[0].lat, FARMERS[0].lng, MARKETS[0].lat, MARKETS[0].lng) + 0.2, abs=1e-3)
    model2, matrix2 = roads.plan_distance_model(conn, FARMERS, MARKETS)
    assert model2 == model and len(osrm) == 1                              # no second provider call


def test_provider_failure_degrades_to_straight_lines(monkeypatch, osrm):
    def boom(*a, **k):
        raise roads.RoutingError("osrm down")
    monkeypatch.setattr(roads, "_fetch_table", boom)
    model, matrix = roads.plan_distance_model(FakeConn(), FARMERS, MARKETS)
    assert matrix is None and model["type"] == "straight" and "osrm down" in model["note"]


def test_switches_off(monkeypatch, osrm):
    model, matrix = roads.plan_distance_model(FakeConn(), FARMERS, MARKETS, enabled=False)
    assert matrix is None and model["type"] == "straight" and not osrm
    monkeypatch.setenv("ROAD_PLANNING", "off")
    assert roads.plan_distance_model(FakeConn(), FARMERS, MARKETS)[1] is None and not osrm
    monkeypatch.delenv("ROAD_PLANNING")
    monkeypatch.setenv("ROUTING_PROVIDER", "off")
    assert roads.plan_distance_model(FakeConn(), FARMERS, MARKETS)[1] is None and not osrm


def test_big_scenarios_use_a_measured_road_factor_instead(monkeypatch, osrm):
    monkeypatch.setenv("ROAD_MATRIX_MAX_POINTS", "3")
    model, matrix = roads.plan_distance_model(FakeConn(), FARMERS, MARKETS)
    assert matrix is None and model["type"] == "circuity" and model["source"] == "road_sample"
    assert 1.0 <= model["k"] <= 3.0 and len(osrm) == 1


# ---- replaying a stored plan's model ----

def _snapshot(model):
    return {"distance_model": model,
            "farmers": [{"lat": f.lat, "lng": f.lng} for f in FARMERS],
            "markets": [{"lat": m.lat, "lng": m.lng} for m in MARKETS]}


def test_replay_uses_exactly_the_distances_the_plan_saw(osrm):
    conn = FakeConn()
    model, planned = roads.plan_distance_model(conn, FARMERS, MARKETS)
    # what the optimizer saw
    with use_road_matrix(planned):
        saw = haversine(FARMERS[1].lat, FARMERS[1].lng, MARKETS[0].lat, MARKETS[0].lng)
    # what the map later sees, rebuilt from the JSON snapshot + cached matrix
    snap = json.loads(json.dumps(_snapshot(model)))                       # real JSON round trip
    with roads.distance_context(conn, snap):
        replay = haversine(FARMERS[1].lat, FARMERS[1].lng, MARKETS[0].lat, MARKETS[0].lng)
    assert replay == saw
    assert haversine(FARMERS[1].lat, FARMERS[1].lng, MARKETS[0].lat, MARKETS[0].lng) != saw   # and it is scoped


def test_replay_of_old_or_circuity_plans(osrm):
    plain = haversine(*P[0], *P[1])
    with roads.distance_context(FakeConn(), {}):                           # plan from before this feature
        assert haversine(*P[0], *P[1]) == plain
    with roads.distance_context(FakeConn(), _snapshot({"type": "circuity", "k": 1.5})):
        assert haversine(*P[0], *P[1]) == pytest.approx(1.5 * crow_km(*P[0], *P[1]))
    assert haversine(*P[0], *P[1]) == plain


def test_replay_with_missing_cache_falls_back_to_measured_ratio(osrm):
    model = {"type": "road_matrix", "key": "gone", "ratio": 1.3}
    with roads.distance_context(FakeConn(), _snapshot(model)):
        assert haversine(*P[0], *P[1]) == pytest.approx(1.3 * crow_km(*P[0], *P[1]))
