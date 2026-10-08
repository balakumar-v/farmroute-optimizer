"""
stress.py -- Monte Carlo stress test of a FINISHED ILO plan (#6).

The plan is replayed (same pools, same vehicles, same planned start hours) under random shocks and every trip is
re-costed by the real simulator (run_our_system_v2: routing, spoilage, market allocation LP), so what comes back is
what the plan would actually earn, not a re-optimised plan. Shocks, per draw:
  travel   one lognormal speed factor for the whole day (traffic / weather): time x exp(N(0, travel_sd))
  ready    each farmer is ready later by |N(0, ready_delay_sd_hr)| hours (deadlines unchanged)
  mandi    each (mandi, crop) price x exp(N(0, mandi_price_sd)), independent
  doorstep each crop's doorstep (farm-gate) price x exp(N(0, farmgate_sd)), independent
  spoilage each crop's hourly spoilage rate x exp(N(0, spoilage_rate_sd)); default 0 (off). Section 23 of the
           results doc shows the rate is the spoilage parameter that matters; 0.4 to 0.7 is a plausible range until
           the rates are measured.
A trip that loses its vehicle or misses a deadline in a draw is not hauled: its farmers sell at the doorstep,
so its gain is 0 in that draw (and it counts in p_lost).

Outputs:
  plan   distribution of total gain over doorstep sales (mean/sd/p5/p50/p95, P(gain<0), expected shortfall),
         the same with nominal (no-noise) replay, and the gain if every trip were chosen ex post (upper bound)
  trips  per trip: p_beat (hauled AND beats doorstep), p_lost, mean/p5 gain, nominal gain
withhold_fragile() then withholds trips whose p_beat < min_prob (default 0.8).
Defaults are judgement calls, not calibrated: set them from your own logs.
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses

import numpy as np

import algorithms_v2 as _A
import baselines_v3 as _B
import ilo_v3 as _I
import logistics_lib_v2 as _L
from algorithms_v2 import _withheld_result, run_our_system_v2
from baselines_v3 import FarmgatePrices

_SPEED_MODULES = (_L, _A, _B, _I)


@contextlib.contextmanager
def _speed_shock(theta):
    """All travel times x theta for the duration (module-level AVG_SPEED_KMPH is imported by name in each module)."""
    saved = {m: m.AVG_SPEED_KMPH for m in _SPEED_MODULES}
    try:
        for m in _SPEED_MODULES:
            m.AVG_SPEED_KMPH = saved[m] / theta
        yield
    finally:
        for m in _SPEED_MODULES:
            m.AVG_SPEED_KMPH = saved[m]


@contextlib.contextmanager
def _crop_spoilage_shock(mult_by_crop):
    """Per-crop multipliers on the hourly spoilage rate for the duration of one replay."""
    saved = {c: _L.CROPS[c]["base_spoil_per_hr"] for c in mult_by_crop}
    try:
        for c, k in mult_by_crop.items():
            _L.CROPS[c]["base_spoil_per_hr"] = saved[c] * k
        yield
    finally:
        for c, r in saved.items():
            _L.CROPS[c]["base_spoil_per_hr"] = r


def monte_carlo_stress(results, farmers, fleet, markets, prices, n_draws=200, seed=0, travel_sd=0.20,
                       ready_delay_sd_hr=1.0, mandi_price_sd=0.08, farmgate_sd=0.08, price_impact=None,
                       spoilage_rate_sd=0.0):
    trips = [r for r in results if r["vehicle_id"] is not None]
    if not trips:
        return {"plan": {"n_draws": 0, "trips": 0}, "trips": []}
    by_id = {f.id: f for f in farmers}
    ids = [list(r["farmer_ids"]) for r in trips]
    keys = [frozenset(i) for i in ids]
    hints = {k: {"vehicle_id": r["vehicle_id"], "start": r.get("dispatch_hr", 0.0)} for k, r in zip(keys, trips)}
    crops = sorted({f.crop for f in farmers})
    run_kw = dict(withhold_uneconomic=False, fix_route_duration=True, spoilage_from_pickup=True,
                  charge_return_leg=True)
    if price_impact is not None:
        run_kw["elastic_pricing"] = price_impact
        run_kw["top_k"] = min(len(markets) * len(price_impact.breakpoints), 30)

    def replay(farmers_k, markets_k, prices_k, theta, spoil_mult=None):
        fk = {f.id: f for f in farmers_k}
        pools = [[fk[i] for i in grp] for grp in ids]
        with _speed_shock(theta), _crop_spoilage_shock(spoil_mult or {}):
            out = run_our_system_v2(farmers_k, copy.deepcopy(fleet), markets_k, raw_pools_override=pools,
                                    pool_hints=hints, **run_kw)
        res_by = {frozenset(r["farmer_ids"]): r for r in out}
        deltas, hauled = [], []
        for grp, k in zip(ids, keys):
            r = res_by.get(k)
            ok = r is not None and r["vehicle_id"] is not None
            hauled.append(ok)
            deltas.append((r["net_return"] - prices_k.value_of([fk[i] for i in grp])) if ok else 0.0)
        return np.array(deltas), np.array(hauled)

    nominal_d, nominal_h = replay(farmers, markets, prices, 1.0)
    D = np.zeros((n_draws, len(trips)))
    H = np.zeros((n_draws, len(trips)), dtype=bool)
    for k in range(n_draws):
        rng = np.random.default_rng(seed * 100003 + k)
        theta = float(np.exp(rng.normal(0.0, travel_sd)))
        farmers_k = [dataclasses.replace(f, ready_hr=f.ready_hr + abs(rng.normal(0.0, ready_delay_sd_hr)))
                     for f in farmers]
        markets_k = [dataclasses.replace(m, price={c: p * float(np.exp(rng.normal(0.0, mandi_price_sd)))
                                                   for c, p in m.price.items()}) for m in markets]
        fg_mult = {c: float(np.exp(rng.normal(0.0, farmgate_sd))) for c in crops}
        prices_k = FarmgatePrices(markets_k, price_fn=lambda f, m=fg_mult: prices.per_kg(f) * m[f.crop])
        spoil_mult = ({c: float(np.exp(rng.normal(0.0, spoilage_rate_sd))) for c in crops}
                      if spoilage_rate_sd > 0 else None)
        D[k], H[k] = replay(farmers_k, markets_k, prices_k, theta, spoil_mult)

    total = D.sum(axis=1)
    beat = H & (D > 0)
    q5 = np.quantile(total, 0.05)
    plan = {"n_draws": n_draws, "trips": len(trips), "nominal_gain": float(nominal_d.sum()),
            "mean_gain": float(total.mean()), "sd_gain": float(total.std()), "p5_gain": float(q5),
            "p50_gain": float(np.quantile(total, 0.5)), "p95_gain": float(np.quantile(total, 0.95)),
            "prob_gain_negative": float((total < 0).mean()),
            "expected_shortfall_5pct": float(total[total <= q5].mean()),
            "gain_if_each_trip_chosen_ex_post": float(np.maximum(D, 0.0).sum(axis=1).mean()),
            "mean_trips_lost": float((~H).sum(axis=1).mean()),
            "shocks": {"travel_sd": travel_sd, "ready_delay_sd_hr": ready_delay_sd_hr,
                       "mandi_price_sd": mandi_price_sd, "farmgate_sd": farmgate_sd,
                       "spoilage_rate_sd": spoilage_rate_sd}}
    per_trip = [{"farmer_ids": ids[j], "vehicle_id": trips[j]["vehicle_id"], "p_beat": float(beat[:, j].mean()),
                 "p_lost": float((~H[:, j]).mean()), "mean_gain": float(D[:, j].mean()),
                 "p5_gain": float(np.quantile(D[:, j], 0.05)), "nominal_gain": float(nominal_d[j])}
                for j in range(len(trips))]
    return {"plan": plan, "trips": per_trip}


def withhold_fragile(results, farmers, mc, min_prob=0.8):
    """Withhold dispatched trips whose Monte Carlo p_beat < min_prob (their farmers sell at the doorstep).
    Returns (new results, number withheld)."""
    fragile = {frozenset(t["farmer_ids"]) for t in mc["trips"] if t["p_beat"] < min_prob}
    by_id = {f.id: f for f in farmers}
    out, n = [], 0
    for r in results:
        if r["vehicle_id"] is not None and frozenset(r["farmer_ids"]) in fragile:
            w = _withheld_result([by_id[i] for i in r["farmer_ids"]])
            w["sold_at_farmgate"] = True
            out.append(w)
            n += 1
        else:
            out.append(r)
    return out, n
