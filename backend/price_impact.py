"""
price_impact.py -- volume-dependent mandi prices for the planner.

MODEL  A mandi-crop's quoted price p0 is its price at a normal day's arrivals V (the data's median daily arrival =
       Market.capacity_kg[crop]). Bringing q extra kg moves the clearing price for everything sold there:
           price(q) = p0 * (1 + q / V) ** (-eta)          revenue(q) = q * price(q)      (concave in q)
       eta is the price flexibility (% price drop per % more arrivals). Revenue is approximated by a few linear
       tranches [(start_kg, width_kg, Rs/kg slope)] with decreasing slopes, so it drops straight into the set-
       partitioning MILP as continuous tranche variables (no binaries) and into the market-allocation LP as demand
       nodes (market_demand_nodes accepts a PriceImpact).

ETA    DEFAULT_ETA comes from within-mandi regressions of log modal price on log arrivals in the Agmarknet files
       under real_data/data/raw (market x crop fixed effects, plus crop x day effects), all five states. Perishables
       come out clearly negative (tomato ~0.09, cauliflower ~0.05-0.1, spinach ~0.08), storables ~0 (onion, potato),
       mango unstable. Treat these as a LOWER BOUND on true flexibility: modal prices and reported arrivals are
       noisy (attenuation) and the data cannot say what ONE extra truck does. Stress with `scale` (the old
       stylized steps [1.0, 0.9, 0.78] over a day's capacity correspond to eta ~ 0.35, i.e. scale ~ 3-4).
       Re-estimate with estimate_price_flexibility() on your own files.
"""
from __future__ import annotations

DEFAULT_ETA = {"tomato": 0.09, "cauliflower": 0.07, "spinach": 0.08, "mango": 0.04, "onion": 0.02, "potato": 0.015}
DEFAULT_ETA_OTHER = 0.05
DEFAULT_BREAKPOINTS = (0.1, 0.25, 0.5, 0.75, 1.0)          # tranche ends, as a share of the mandi-crop's capacity
SOFT_BREAKPOINTS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)   # soft capacity: tranches continue beyond a normal day


class PriceImpact:
    def __init__(self, eta=None, scale=1.0, breakpoints=DEFAULT_BREAKPOINTS, ref_scale=1.0, capacity_multiple=None):
        """capacity_multiple=None keeps the legacy HARD capacity: a mandi-crop takes at most its `capacity_kg` (a
        normal day's arrivals). capacity_multiple=M > 1 makes it SOFT: it keeps taking volume up to M x capacity, at
        the falling price (1 + q/V)^-eta, so the cap becomes a price rather than a wall."""
        self.eta = dict(DEFAULT_ETA if eta is None else eta)
        self.scale = float(scale)
        if capacity_multiple is not None:
            assert capacity_multiple >= 1.0
            breakpoints = [b for b in SOFT_BREAKPOINTS if b < capacity_multiple] + [float(capacity_multiple)]
        self.breakpoints = tuple(breakpoints)
        self.ref_scale = float(ref_scale)
        assert self.scale >= 0 and self.ref_scale > 0 and self.breakpoints[-1] >= 1.0

    @classmethod
    def soft(cls, multiple=3.0, **kw):
        return cls(capacity_multiple=multiple, **kw)

    @property
    def capacity_multiple(self):
        """Hard ceiling on volume per mandi-crop, as a multiple of Market.capacity_kg (1.0 = the legacy cap)."""
        return self.breakpoints[-1]

    def eta_of(self, crop):
        return self.scale * self.eta.get(crop, DEFAULT_ETA_OTHER)

    def _ref(self, m, crop):
        return self.ref_scale * m.capacity_kg[crop]

    def multiplier(self, m, crop, q):
        return (1.0 + max(q, 0.0) / self._ref(m, crop)) ** (-self.eta_of(crop))

    def revenue(self, m, crop, q):
        """Rs from selling q (effective) kg at mandi m, everyone's price moved by the extra volume."""
        return m.price[crop] * q * self.multiplier(m, crop, q)

    def tranches(self, m, crop):
        """[(start_kg, width_kg, Rs/kg)] covering 0..capacity_multiple x capacity; slopes are non-increasing."""
        cap = m.capacity_kg[crop]
        out, a = [], 0.0
        for b in self.breakpoints:
            end = b * cap
            w = end - a
            if w > 1e-9:
                out.append((a, w, (self.revenue(m, crop, end) - self.revenue(m, crop, a)) / w))
            a = end
        return out

    def tranche_nodes(self, m, crop):
        """Demand nodes for allocate_markets_lp (same shape as market_demand_nodes' elastic nodes)."""
        return [{"market": m, "capacity_kg": w, "price": s} for _a, w, s in self.tranches(m, crop)]


def estimate_price_flexibility(csv_paths, min_obs=15, min_rows=150):
    """Re-estimate eta per crop from Agmarknet IDP CSVs (columns as in real_data/data/raw). Returns
    {crop: {"eta": max(0, -b), "b": slope, "se": s.e., "n": rows}} from log(price) ~ log(arrivals) with
    market x crop and crop x day fixed effects. Needs pandas. Slopes are attenuated by measurement error and
    contaminated by demand shocks; read them as a lower bound and stress-test with PriceImpact(scale=...)."""
    import numpy as np
    import pandas as pd
    frames = []
    for p in csv_paths:
        d = pd.read_csv(p)
        d = d[(d.unit_name_price == "Rs./Quintal") & (d.unit_name_arrival == "Metric Tonnes")
              & (d.model_price > 0) & (d.arrival_qty > 0)].copy()
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d["lp"], d["la"] = np.log(d.model_price), np.log(d.arrival_qty)
    d = d[d.groupby(["market_name", "crop"]).arrival_date.transform("count") >= min_obs]
    out = {}
    for crop, dc in d.groupby("crop"):
        if len(dc) < min_rows:
            continue
        y, x = dc.lp.values.copy(), dc.la.values.copy()
        g = [dc.groupby(["market_name"]).ngroup().values, dc.groupby(["arrival_date"]).ngroup().values]
        for _ in range(8):
            for gg in g:
                for v in (y, x):
                    v -= pd.Series(v).groupby(gg).transform("mean").values
        b = float((x * y).sum() / (x * x).sum())
        se = float(np.sqrt(((y - b * x) ** 2).sum() / (len(y) - 1) / (x * x).sum()))
        out[crop] = {"eta": max(0.0, -b), "b": b, "se": se, "n": int(len(dc))}
    return out
