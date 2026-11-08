"""Shared protocol for the ILO v3 improvement study (experiments/v4).
Same scenario, seed and road matrix for every variant. Roads are a SYNTHETIC road network (no OSRM egress in the
sandbox): jittered lattice, ~25% edges removed, a few fast corridors, all-pairs Dijkstra -> a true metric."""
import os, sys, time, copy, random, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from logistics_lib_v2 import (generate_scenario_v2, RoadMatrix, use_road_matrix, crow_km)
from baselines_v3 import FarmgatePrices, run_farmgate_baseline_v2, summarize_with_farmgate
import ilo_v3

DISCOUNT = 0.20


def make_road_matrix(farmers, markets, seed, grid=32, drop=0.08):
    pts = [(f.lat, f.lng) for f in farmers] + [(m.lat, m.lng) for m in markets]
    rng = np.random.default_rng(10_000 + seed)
    P = np.array(pts)
    lo, hi = P.min(0) - 0.01, P.max(0) + 0.01
    gx, gy = np.meshgrid(np.linspace(lo[0], hi[0], grid), np.linspace(lo[1], hi[1], grid), indexing="ij")
    step = (hi - lo) / (grid - 1)
    nodes = np.c_[gx.ravel(), gy.ravel()] + rng.uniform(-0.3, 0.3, (grid * grid, 2)) * step
    idx = lambda i, j: i * grid + j
    rows, cols, w = [], [], []
    def add(a, b, fast=1.0):
        d = crow_km(*nodes[a], *nodes[b]) * rng.uniform(1.0, 1.10) / fast
        rows.extend([a, b]); cols.extend([b, a]); w.extend([d, d])
    for i in range(grid):
        for j in range(grid):
            if i + 1 < grid and rng.random() > drop: add(idx(i, j), idx(i + 1, j))
            if j + 1 < grid and rng.random() > drop: add(idx(i, j), idx(i, j + 1))
    for _ in range(grid // 4):                                    # highway corridors: long cheap edges
        a, b = rng.integers(0, grid * grid, 2)
        d = crow_km(*nodes[a], *nodes[b]) * 1.05
        rows.extend([a, b]); cols.extend([b, a]); w.extend([d, d])
    G = coo_matrix((w, (rows, cols)), shape=(grid * grid,) * 2).tocsr()
    D = dijkstra(G, directed=False)
    from scipy.spatial import cKDTree
    tree = cKDTree(nodes)
    _, near = tree.query(P)
    conn = np.array([crow_km(*P[i], *nodes[near[i]]) for i in range(len(P))])
    n = len(P)
    km = D[np.ix_(near, near)] + conn[:, None] + conn[None, :]
    straight = np.array([[crow_km(*P[i], *P[j]) for j in range(n)] for i in range(n)])
    km = np.where(np.isfinite(km), np.maximum(km, straight), straight * 1.6)   # unreachable -> 1.6x straight
    np.fill_diagonal(km, 0.0)
    off = straight > 1.0
    ratio = float(np.median(km[off] / straight[off]))
    return RoadMatrix({p: i for i, p in enumerate(pts)}, km.tolist(), min(3.0, max(1.0, ratio))), ratio


_CACHE = {}
CENTER = (25.60, 84.90)
def scenario(n, seed, family="G"):
    key = (n, seed, family)
    if key not in _CACHE:
        farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=max(3, n // 300 + 2), seed=seed)
        if family == "D" and n > 60:                      # dense: squeeze everything into the n=60 footprint
            s = math.sqrt(60.0 / n)
            for f in farmers:
                f.lat = CENTER[0] + s * (f.lat - CENTER[0]); f.lng = CENTER[1] + s * (f.lng - CENTER[1])
            for m in markets:
                m.lat = CENTER[0] + s * (m.lat - CENTER[0]); m.lng = CENTER[1] + s * (m.lng - CENTER[1])
        rm, ratio = make_road_matrix(farmers, markets, seed)
        _CACHE[key] = (farmers, fleet, markets, rm, ratio)
    f, fl, m, rm, ratio = _CACHE[key]
    return f, copy.deepcopy(fl), m, rm, ratio


def score(res, farmers, markets, fleet, prices):
    return summarize_with_farmgate(res, farmers, markets, len(fleet), prices=prices)["net_return_incl_farmgate"]


def run(n, seed, env=None, family="G", **kw):
    """Run ILO v3 under road matrix + env switches. Returns dict(value, fg, gain, secs, chosen, meta)."""
    farmers, fleet, markets, rm, ratio = scenario(n, seed, family)
    prices = FarmgatePrices(markets, DISCOUNT)
    env = dict(env or {})
    turn = env.pop("TURNAROUND", None)                      # sensitivity: flat vehicle turnaround (hours), ILO's fleet clock
    import logistics_lib_v2 as L, algorithms_v2 as A
    saved_t = (L.TURNAROUND_HR, A.TURNAROUND_HR, ilo_v3.TURNAROUND_HR)
    if turn is not None:
        L.TURNAROUND_HR = A.TURNAROUND_HR = ilo_v3.TURNAROUND_HR = float(turn)
    old = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        with use_road_matrix(rm):
            fg = score(run_farmgate_baseline_v2(farmers, markets), farmers, markets, fleet, prices)
            t0 = time.time()
            res, meta = ilo_v3.run_ilo_v3(farmers, fleet, markets, discount=DISCOUNT, return_meta=True, **kw)
            secs = time.time() - t0
            val = score(res, farmers, markets, fleet, prices)
    finally:
        L.TURNAROUND_HR, A.TURNAROUND_HR, ilo_v3.TURNAROUND_HR = saved_t
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    return dict(n=n, seed=seed, family=family, value=val, fg=fg, gain=val - fg, secs=secs, chosen=meta["chosen"], meta=meta, ratio=ratio)
