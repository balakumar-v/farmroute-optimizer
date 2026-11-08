"""Road-circuity model: scaling, restore, calibration fit, and that thresholds stay road-km."""
import csv
import io
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import logistics_lib_v2 as L
from algorithms_v2 import _dbscan_clusters
from calibrate_circuity import fit
from logistics_lib_v2 import Farmer


def test_haversine_scales_and_context_restores():
    base = L.crow_km(25.9, 85.2, 26.0, 85.3)
    assert L.haversine(25.9, 85.2, 26.0, 85.3) == pytest.approx(base)          # default = legacy straight line
    with L.road_circuity(1.4):
        assert L.haversine(25.9, 85.2, 26.0, 85.3) == pytest.approx(1.4 * base)
    assert L.get_road_circuity() == 1.0


def test_invalid_circuity_rejected():
    for bad in (0.5, 3.5):
        with pytest.raises(ValueError):
            L.set_road_circuity(bad)
    assert L.get_road_circuity() == 1.0


def test_calibration_recovers_the_factor():
    rng = random.Random(1)
    rows = []
    for _ in range(300):
        lat1, lng1 = 25 + rng.random(), 85 + rng.random()
        lat2, lng2 = lat1 + rng.uniform(-.2, .2), lng1 + rng.uniform(-.2, .2)
        d = L.crow_km(lat1, lng1, lat2, lng2)
        rows.append(dict(lat1=lat1, lng1=lng1, lat2=lat2, lng2=lng2, road_km=d * rng.uniform(1.25, 1.35)))
    res = fit(rows)
    assert res["road_circuity"] == pytest.approx(1.3, abs=0.03)
    assert res["p10"] < res["road_circuity"] < res["p90"]


def test_clustering_radius_is_road_km():
    # two farmers 10 km apart in a straight line: one cluster at eps=12 road-km when circuity=1,
    # but 14 road-km apart at circuity 1.4 -> two clusters
    f = [Farmer(id=0, lat=25.0, lng=85.0, crop="potato", qty_kg=100, ready_hr=1, deadline_hr=14, needs_refrigeration=False),
         Farmer(id=1, lat=25.0, lng=85.0 + 10.0 / (111.19 * math.cos(math.radians(25.0))), crop="potato",
                qty_kg=100, ready_hr=1, deadline_hr=14, needs_refrigeration=False)]
    assert len(_dbscan_clusters(f, eps_km=12.0)) == 1
    with L.road_circuity(1.4):
        assert len(_dbscan_clusters(f, eps_km=12.0)) == 2
