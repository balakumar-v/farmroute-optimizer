"""Pure tests for roads.py -- no network, no database."""
import pytest

import logistics_lib_v2 as lib
import roads

A = {"lat": 25.0, "lng": 84.0}
B = {"lat": 25.0, "lng": 84.1}
C = {"lat": 25.1, "lng": 84.1}

# OSRM /route response (steps=true, geometries=geojson), 2 legs: A->B east, B->C north.
OSRM = {
    "code": "Ok",
    "routes": [{
        "distance": 20000, "duration": 1,
        "legs": [
            {"distance": 10100.0, "steps": [
                {"geometry": {"type": "LineString", "coordinates": [[84.0003, 25.0001], [84.05, 25.0001]]}},
                {"geometry": {"type": "LineString", "coordinates": [[84.05, 25.0001], [84.0995, 25.0002]]}},
                {"geometry": {"type": "LineString", "coordinates": [[84.0995, 25.0002]]}},
            ]},
            {"distance": 11000.0, "steps": [
                {"geometry": {"type": "LineString", "coordinates": [[84.0995, 25.0002], [84.0996, 25.05]]}},
                {"geometry": {"type": "LineString", "coordinates": [[84.0996, 25.05], [84.0997, 25.0998]]}},
            ]},
        ],
    }],
    "waypoints": [],
}

# ORS /v2/directions/driving-car/geojson response.
ORS = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {
            "segments": [{"distance": 10100.0, "duration": 1}, {"distance": 11000.0, "duration": 1}],
            "way_points": [0, 3, 6],
        },
        "geometry": {"type": "LineString", "coordinates": [
            [84.0003, 25.0001], [84.05, 25.0001], [84.08, 25.0001], [84.0995, 25.0002],
            [84.0996, 25.05], [84.0996, 25.08], [84.0997, 25.0998],
        ]},
    }],
}


def test_parse_osrm_splits_legs_and_dedupes_joint_points():
    coords, wps, dists = roads.parse_osrm(OSRM)
    assert dists == [10100.0, 11000.0]
    assert len(wps) == 3 and wps[0] == 0
    assert coords[wps[1]] == [84.0995, 25.0002]
    assert coords[wps[2]] == [84.0997, 25.0998]
    assert all(coords[i] != coords[i + 1] for i in range(len(coords) - 1))


def test_parse_osrm_error_code_raises():
    with pytest.raises(roads.RoutingError):
        roads.parse_osrm({"code": "NoRoute", "message": "no route"})


def test_parse_ors():
    coords, wps, dists = roads.parse_ors(ORS)
    assert wps == [0, 3, 6] and dists == [10100.0, 11000.0] and len(coords) == 7


def test_parse_ors_empty_raises():
    with pytest.raises(roads.RoutingError):
        roads.parse_ors({"features": []})


def test_assemble_legs_starts_and_ends_at_exact_stops_with_connectors():
    coords, wps, dists = roads.parse_ors(ORS)
    legs = roads.assemble_legs([A, B, C], coords, wps, dists)
    assert len(legs) == 2
    assert legs[0]["coordinates"][0] == [84.0, 25.0] and legs[0]["coordinates"][-1] == [84.1, 25.0]
    assert legs[1]["coordinates"][0] == [84.1, 25.0] and legs[1]["coordinates"][-1] == [84.1, 25.1]
    for leg in legs:
        assert leg["offRoadKm"] > 0
        assert leg["distanceKm"] >= leg["offRoadKm"]
    # road distance + connectors, not just the provider number
    assert legs[0]["distanceKm"] == pytest.approx(10.1 + legs[0]["offRoadKm"], abs=1e-3)


def test_assemble_legs_rejects_mismatched_response():
    coords, wps, dists = roads.parse_ors(ORS)
    with pytest.raises(roads.RoutingError):
        roads.assemble_legs([A, B], coords, wps, dists)          # 2 stops but 3 waypoints
    with pytest.raises(roads.RoutingError):
        roads.assemble_legs([A, B, C], coords, [0, 6, 3], dists)  # decreasing indices


def test_connector_length_ignores_planner_circuity():
    coords, wps, dists = roads.parse_ors(ORS)
    base = roads.assemble_legs([A, B, C], coords, wps, dists)[0]["offRoadKm"]
    lib.set_road_circuity(1.6)
    try:
        scaled = roads.assemble_legs([A, B, C], coords, wps, dists)[0]["offRoadKm"]
    finally:
        lib.set_road_circuity(1.0)
    assert scaled == base


def test_simplify_drops_collinear_keeps_corner_and_endpoints():
    path = [[84.0, 25.0], [84.02, 25.0], [84.04, 25.0], [84.06, 25.0], [84.06, 25.05], [84.06, 25.1]]
    out = roads.simplify(path, 5.0)
    assert out[0] == path[0] and out[-1] == path[-1]
    assert [84.06, 25.0] in out
    assert len(out) == 3


def test_route_key_stable_and_provider_specific():
    k1 = roads.route_key("osrm", "driving", [A, B])
    assert k1 == roads.route_key("osrm", "driving", [dict(A), dict(B)])
    assert k1 != roads.route_key("ors", "driving", [A, B])
    assert k1 != roads.route_key("osrm", "driving", [B, A])       # direction matters (one-way roads)
    assert k1 == roads.route_key("osrm", "driving", [{"lat": 25.0000001, "lng": 84.0}, B])  # 5-dp rounding


def test_provider_selection(monkeypatch):
    for v in ("ROUTING_PROVIDER", "ORS_API_KEY", "ROUTING_PROFILE"):
        monkeypatch.delenv(v, raising=False)
    assert roads.provider_name() == "osrm" and roads.profile_name() == "driving"
    monkeypatch.setenv("ORS_API_KEY", "k")
    assert roads.provider_name() == "ors" and roads.profile_name() == "driving-car"
    monkeypatch.setenv("ROUTING_PROVIDER", "off")
    assert roads.provider_name() is None


def test_fetch_route_end_to_end_with_stubbed_http(monkeypatch):
    monkeypatch.setattr(roads, "_http_json", lambda *a, **k: OSRM)
    legs = roads.fetch_route("osrm", "driving", [A, B, C])
    assert len(legs) == 2 and legs[0]["coordinates"][0] == [84.0, 25.0]
