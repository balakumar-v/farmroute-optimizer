"""Shared helpers for the trip-structure experiments (run scripts from backend/)."""
import sys
import numpy as np
sys.path.insert(0, '.')
import ilo_v3 as I


def add_mixed(cands, farmers, fleet, markets, prices):
    """Add Clarke-Wright trips mixing crops of the same refrigeration class (ilo_v3 builds one-crop routes only)."""
    vt = I._fleet_types(fleet)
    per_km = float(np.mean([v.per_km_cost for v in fleet]))
    q_ref = float(np.median([v.capacity_kg for v in fleet])) * 0.8
    qany = max(v.capacity_kg for v in fleet)
    qref = max((v.capacity_kg for v in fleet if v.refrigerated), default=qany)
    for m in markets:
        for refrig in (True, False):
            F = [f for f in farmers if f.needs_refrigeration == refrig and f.crop in m.price and f.crop in m.capacity_kg]
            F = I._eligible_for_market(F, m, markets, per_km, q_ref)
            if len(F) < 2:
                continue
            for order in I._cw_routes(F, m, qref if refrig else qany):
                if len({f.crop for f in order}) < 2:
                    continue
                c = I._eval_trip(order, markets, prices, vt, 0.0, m)
                if c is not None and c["delta"] > 1e-6 and (c["ids"] not in cands or c["delta"] > cands[c["ids"]]["delta"] + 1e-6):
                    c["source"] = "cw_mixed"
                    cands[c["ids"]] = c
    return cands


orig_gen = I.generate_candidates


def gen_mixed(farmers, fleet, markets, prices, margin, consolidate=True):
    cands, stats = orig_gen(farmers, fleet, markets, prices, margin, consolidate)
    return add_mixed(cands, farmers, fleet, markets, prices), stats
