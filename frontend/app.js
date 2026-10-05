const LABELS = ["Integrated Logistics Optimization", "Proximity Pooling", "Individual Transport"];
const KEYS = ["integrated_logistics_optimization", "proximity_pooling", "individual_transport"];

// Mirrors CROPS / VEHICLE_TYPES in backend/logistics_lib_v2.py. The API has
// no "list valid crops/vehicle types" endpoint, so these are kept in sync
// by hand -- if that file's tables change, update these too.
const CROPS = ["tomato", "onion", "potato", "cauliflower", "mango", "spinach"];
const VEHICLE_TYPES = [
  { name: "mini_pickup", capacity_kg: 500, refrigerated: false, fixed_cost: 500, per_km_cost: 14 },
  { name: "van", capacity_kg: 1000, refrigerated: false, fixed_cost: 900, per_km_cost: 18 },
  { name: "reefer_van", capacity_kg: 1000, refrigerated: true, fixed_cost: 1300, per_km_cost: 21 },
  { name: "truck_2t", capacity_kg: 2000, refrigerated: false, fixed_cost: 1700, per_km_cost: 20 },
  { name: "reefer_2t", capacity_kg: 2000, refrigerated: true, fixed_cost: 2200, per_km_cost: 24 },
  { name: "truck_5t", capacity_kg: 5000, refrigerated: false, fixed_cost: 3200, per_km_cost: 27 },
  { name: "reefer_5t", capacity_kg: 5000, refrigerated: true, fixed_cost: 4000, per_km_cost: 32 },
];

const state = {
  apiBase: "http://localhost:8000",
  lastPlan: null,
  charts: { net: null, cov: null }
};

// Small, additive bridge for frontend/vis/*.js (the Map & Simulation tab).
// Those files are loaded after this one and are a separate concern (they
// know nothing about pools/algorithms internals, only about the
// /plan/{id}/visualization endpoint), but they need to know which plan was
// last computed and which API base to call -- rather than duplicating
// CROPS/VEHICLE_TYPES/apiBase tracking, this just republishes what already
// exists here. Nothing above this point changes.
window.FPO = window.FPO || {};
window.FPO.CROPS = CROPS;
window.FPO.VEHICLE_TYPES = VEHICLE_TYPES;
window.FPO.ALGO_LABELS = LABELS;
window.FPO.ALGO_KEYS = KEYS;
window.FPO.getApiBase = () => state.apiBase;
window.FPO.getLastPlanId = () => state.lastPlan?.id ?? null;
window.FPO.onPlanComputed = null; // frontend/vis/mapview.js sets this if loaded

// ---------- demo scenarios ----------
// Each scenario isolates ONE specific mechanism in algorithms_v2.py where
// Integrated Logistics Optimization structurally differs from the two
// baselines -- not just "different random data". The three synthetic ones were tuned and
// verified by running the actual algorithm code directly (not guessed):
// see the project chat history for the harness and results.
//
// NOTE (applies to every scenario): the allocation LP (market_demand_nodes
// in logistics_lib_v2.py) looks up m.capacity_kg[crop]/m.price[crop] for
// EVERY market against every crop that appears among the farmers, with no
// per-market filtering -- a market missing even one such crop key crashes
// /plan/compute with a 500 (KeyError). Every market below quotes every
// crop its scenario's farmers grow, for that reason.
// Preset categories, in the order they appear in the dropdown. To add a preset to a category,
// give it `category: "<id>"`. To add a new category, add an entry here. A category with no presets
// is hidden; presets with a missing/unknown category still appear, under "Other".
//   synthetic = designed scenarios that isolate one mechanism (generated data)
//   real      = real market data (see each preset's blurb for exactly which parts are real)
const SCENARIO_CATEGORIES = [
  { id: "synthetic", label: "Synthetic scenarios" },
  { id: "real", label: "Real data" },
];
const SCENARIOS = {
  cold_chain: {
    label: "1. Cold chain: refrigeration-aware pooling",
    category: "synthetic",
    blurb: "11 farmers, all growing crops that need refrigeration, against a fleet with only ONE refrigerated vehicle (plus 3 ordinary trucks). Watch spoilage (kg) and farmer value: both baselines hire ordinary (non-refrigerated) trucks and never check whether a load needs refrigeration, so perishables ride unrefrigerated. At these short distances (mandis about 6 km away) spoilage is small and the baselines finish about level with ILO, so this scenario shows the mechanism, not a win.",
    // Vehicle order matters here: van is listed before reefer_van so a
    // capacity tie between them (both 1000kg) resolves toward the
    // non-refrigerated option for the refrigeration-BLIND baseline
    // (Proximity Pooling) -- otherwise it can win a tie by list-order
    // luck alone and mask the very effect this scenario is testing.
    farmers: [
      { lat: 25.610, lng: 84.915, crop: "tomato",      qty_kg: 280, ready_hr: 0.0, deadline_hr: 12.0 },
      { lat: 25.615, lng: 84.920, crop: "spinach",     qty_kg: 220, ready_hr: 0.3, deadline_hr: 10.0 },
      { lat: 25.605, lng: 84.910, crop: "cauliflower", qty_kg: 260, ready_hr: 0.6, deadline_hr: 12.0 },
      { lat: 25.612, lng: 84.905, crop: "mango",       qty_kg: 240, ready_hr: 1.0, deadline_hr: 11.0 },
      { lat: 25.618, lng: 84.918, crop: "tomato",      qty_kg: 300, ready_hr: 2.5, deadline_hr: 13.0 },
      { lat: 25.608, lng: 84.912, crop: "spinach",     qty_kg: 210, ready_hr: 2.8, deadline_hr: 11.0 },
      { lat: 25.614, lng: 84.908, crop: "cauliflower", qty_kg: 250, ready_hr: 3.1, deadline_hr: 13.0 },
      { lat: 25.611, lng: 84.922, crop: "mango",       qty_kg: 230, ready_hr: 5.0, deadline_hr: 13.5 },
      { lat: 25.617, lng: 84.913, crop: "tomato",      qty_kg: 290, ready_hr: 5.3, deadline_hr: 14.0 },
      { lat: 25.606, lng: 84.917, crop: "spinach",     qty_kg: 200, ready_hr: 5.6, deadline_hr: 13.0 },
      { lat: 25.613, lng: 84.911, crop: "cauliflower", qty_kg: 240, ready_hr: 6.0, deadline_hr: 13.5 },
    ],
    vehicles: [
      { type_name: "van", count: 2 },
      { type_name: "mini_pickup", count: 1 },
      { type_name: "reefer_van", count: 1 },
    ],
    markets: [
      { lat: 25.650, lng: 84.950,
        price: { tomato: 22, spinach: 25, cauliflower: 18, mango: 32 },
        capacity_kg: { tomato: 3000, spinach: 3000, cauliflower: 3000, mango: 3000 } },
      { lat: 25.570, lng: 84.860,
        price: { tomato: 20, spinach: 23, cauliflower: 16, mango: 30 },
        capacity_kg: { tomato: 3000, spinach: 3000, cauliflower: 3000, mango: 3000 } },
    ],
  },

  market_arbitrage: {
    label: "2. Market allocation: price/capacity arbitrage",
    category: "synthetic",
    blurb: "10 onion farmers vs. one small high-price market, one mid-price/mid-capacity market, and one large low-price wholesale market -- total supply is over 4x the best market's capacity. Watch coverage (%) and net return: the baselines can't reroute overflow to the next-best market once their first choice fills up, so most of the crop goes completely unsold.",
    farmers: [
      { lat: 25.610, lng: 84.915, crop: "onion", qty_kg: 320, ready_hr: 0.0, deadline_hr: 12.0 },
      { lat: 25.613, lng: 84.918, crop: "onion", qty_kg: 300, ready_hr: 0.3, deadline_hr: 12.0 },
      { lat: 25.607, lng: 84.911, crop: "onion", qty_kg: 340, ready_hr: 0.6, deadline_hr: 12.0 },
      { lat: 25.615, lng: 84.920, crop: "onion", qty_kg: 280, ready_hr: 0.9, deadline_hr: 12.0 },
      { lat: 25.605, lng: 84.908, crop: "onion", qty_kg: 310, ready_hr: 1.2, deadline_hr: 12.0 },
      { lat: 25.617, lng: 84.913, crop: "onion", qty_kg: 330, ready_hr: 1.5, deadline_hr: 12.0 },
      { lat: 25.609, lng: 84.917, crop: "onion", qty_kg: 290, ready_hr: 1.8, deadline_hr: 12.0 },
      { lat: 25.612, lng: 84.906, crop: "onion", qty_kg: 300, ready_hr: 2.1, deadline_hr: 12.0 },
      { lat: 25.616, lng: 84.922, crop: "onion", qty_kg: 320, ready_hr: 2.4, deadline_hr: 12.0 },
      { lat: 25.606, lng: 84.914, crop: "onion", qty_kg: 300, ready_hr: 2.7, deadline_hr: 12.0 },
    ],
    vehicles: [
      { type_name: "truck_2t", count: 2 },
      { type_name: "van", count: 2 },
    ],
    markets: [
      { lat: 25.625, lng: 84.930, price: { onion: 26 }, capacity_kg: { onion: 700 } },   // premium, close, tiny capacity
      { lat: 25.700, lng: 84.850, price: { onion: 19 }, capacity_kg: { onion: 1500 } },  // mid price/distance/capacity
      { lat: 25.450, lng: 85.100, price: { onion: 15 }, capacity_kg: { onion: 5000 } },  // wholesale, far, huge capacity
    ],
  },

  fleet_scarcity: {
    label: "3. Fleet scarcity + incompatible pickup windows",
    category: "synthetic",
    blurb: "15 potato farmers split into a morning group (ready hour 0, strict deadline by hour ~3-4) and an afternoon group (ready hour ~6-7.5, deadline by hour ~12-13.5) in the same neighborhood, sharing only 3 vehicles (the baselines hire their own trucks, so only ILO is held to that fleet). Watch coverage (%) and farmer value: ILO leaves some produce unhauled rather than run losing trips, while Proximity Pooling groups purely by location, waits for the last member, and so the strict-deadline morning farmers miss their pickup and sell at the farm gate.",
    farmers: [
      // morning group -- tight window
      { lat: 25.610, lng: 84.915, crop: "potato", qty_kg: 260, ready_hr: 0.0, deadline_hr: 3.0 },
      { lat: 25.613, lng: 84.918, crop: "potato", qty_kg: 300, ready_hr: 0.2, deadline_hr: 3.5 },
      { lat: 25.607, lng: 84.911, crop: "potato", qty_kg: 280, ready_hr: 0.4, deadline_hr: 3.0 },
      { lat: 25.615, lng: 84.920, crop: "potato", qty_kg: 320, ready_hr: 0.1, deadline_hr: 4.0 },
      { lat: 25.605, lng: 84.908, crop: "potato", qty_kg: 270, ready_hr: 0.3, deadline_hr: 3.5 },
      { lat: 25.617, lng: 84.913, crop: "potato", qty_kg: 290, ready_hr: 0.0, deadline_hr: 3.0 },
      { lat: 25.609, lng: 84.917, crop: "potato", qty_kg: 310, ready_hr: 0.5, deadline_hr: 4.0 },
      // afternoon group -- same neighborhood, incompatible window
      { lat: 25.611, lng: 84.916, crop: "potato", qty_kg: 300, ready_hr: 6.5, deadline_hr: 12.0 },
      { lat: 25.614, lng: 84.919, crop: "potato", qty_kg: 280, ready_hr: 6.8, deadline_hr: 12.5 },
      { lat: 25.606, lng: 84.910, crop: "potato", qty_kg: 320, ready_hr: 7.0, deadline_hr: 13.0 },
      { lat: 25.616, lng: 84.921, crop: "potato", qty_kg: 260, ready_hr: 6.2, deadline_hr: 12.0 },
      { lat: 25.604, lng: 84.907, crop: "potato", qty_kg: 290, ready_hr: 7.2, deadline_hr: 13.5 },
      { lat: 25.618, lng: 84.914, crop: "potato", qty_kg: 300, ready_hr: 6.5, deadline_hr: 12.5 },
      { lat: 25.608, lng: 84.918, crop: "potato", qty_kg: 270, ready_hr: 7.5, deadline_hr: 13.0 },
      { lat: 25.612, lng: 84.909, crop: "potato", qty_kg: 310, ready_hr: 6.8, deadline_hr: 13.0 },
    ],
    vehicles: [
      { type_name: "truck_2t", count: 2 },
      { type_name: "van", count: 1 },
    ],
    markets: [
      { lat: 25.660, lng: 84.960, price: { potato: 13 }, capacity_kg: { potato: 6000 } },
      { lat: 25.560, lng: 84.870, price: { potato: 11 }, capacity_kg: { potato: 6000 } },
    ],
  },
  // ---- Real data ----
  bihar_dec2025_feb2026: {
    category: "real",
    label: "Bihar mandis, Dec 2025 - Feb 2026: potato & onion",
    blurb: "REAL: 8 Bihar mandis (Aarah, Piro, Tajpur, Natwar, Buxar, Chakia, Sheohar, Sasaram) with potato/onion prices from Agmarknet via India Data Portal, 1 Dec 2025 - 28 Feb 2026 (median daily modal price; one window for every mandi so prices are from the same season). Capacity is the median reported daily arrival, a proxy and not a limit: Aarah, Tajpur, Natwar, Buxar and Chakia repeat one value on 95%+ of days, so treat their capacity as an assumption. Piro (Bhojpur, the farmers' own district) stopped reporting on 23 Feb, so its prices rest on 18 days. Coordinates: OpenStreetMap; Piro and Natwar from public place listings (Natwar is uncertain by ~9 km). Left out: Barahat (184 km+ from every farmer) and Brahmpur, Motihari, Bahadurganj (reported prices but no reliable coordinates). SYNTHETIC: the 34 farmers (same generator and seed as the previous preset, so only the mandis changed) and the 8-vehicle fleet; no public farmer or fleet data exists. The farm-gate price used in the comparison is an assumption.",
    farmers: [
      { lat: 25.70438, lng: 84.67999, crop: "onion", qty_kg: 559.4, ready_hr: 3.02, deadline_hr: 16.89 },
      { lat: 25.54195, lng: 84.99778, crop: "potato", qty_kg: 560.9, ready_hr: 0.4, deadline_hr: 14.14 },
      { lat: 25.3888, lng: 85.16898, crop: "potato", qty_kg: 396.9, ready_hr: 3.46, deadline_hr: 9.57 },
      { lat: 25.25526, lng: 84.94521, crop: "potato", qty_kg: 468.0, ready_hr: 3.73, deadline_hr: 14.11 },
      { lat: 25.48549, lng: 85.32373, crop: "potato", qty_kg: 166.4, ready_hr: 1.56, deadline_hr: 7.74 },
      { lat: 25.60321, lng: 84.49382, crop: "onion", qty_kg: 195.4, ready_hr: 0.72, deadline_hr: 14.63 },
      { lat: 25.54913, lng: 84.61325, crop: "onion", qty_kg: 362.2, ready_hr: 2.39, deadline_hr: 11.67 },
      { lat: 25.43373, lng: 84.77403, crop: "potato", qty_kg: 526.9, ready_hr: 2.03, deadline_hr: 10.04 },
      { lat: 25.81302, lng: 84.75531, crop: "potato", qty_kg: 170.6, ready_hr: 0.05, deadline_hr: 8.3 },
      { lat: 25.82529, lng: 85.23851, crop: "potato", qty_kg: 372.6, ready_hr: 2.25, deadline_hr: 10.74 },
      { lat: 25.9307, lng: 85.17549, crop: "potato", qty_kg: 234.6, ready_hr: 3.24, deadline_hr: 17.23 },
      { lat: 25.79164, lng: 84.46117, crop: "onion", qty_kg: 520.2, ready_hr: 0.85, deadline_hr: 11.08 },
      { lat: 25.64275, lng: 84.71782, crop: "onion", qty_kg: 365.1, ready_hr: 1.58, deadline_hr: 9.5 },
      { lat: 25.96036, lng: 84.87708, crop: "onion", qty_kg: 528.4, ready_hr: 0.4, deadline_hr: 14.21 },
      { lat: 25.77601, lng: 84.83522, crop: "onion", qty_kg: 285.9, ready_hr: 1.92, deadline_hr: 13.79 },
      { lat: 25.58996, lng: 84.97486, crop: "potato", qty_kg: 455.7, ready_hr: 1.79, deadline_hr: 11.18 },
      { lat: 25.38917, lng: 85.14435, crop: "onion", qty_kg: 344.0, ready_hr: 3.95, deadline_hr: 12.82 },
      { lat: 25.86905, lng: 85.12737, crop: "potato", qty_kg: 595.7, ready_hr: 2.71, deadline_hr: 14.69 },
      { lat: 25.79152, lng: 85.05303, crop: "potato", qty_kg: 218.1, ready_hr: 3.45, deadline_hr: 17.35 },
      { lat: 25.50008, lng: 84.50057, crop: "onion", qty_kg: 361.9, ready_hr: 2.45, deadline_hr: 9.66 },
      { lat: 25.59146, lng: 85.23622, crop: "onion", qty_kg: 424.6, ready_hr: 3.11, deadline_hr: 12.84 },
      { lat: 25.99222, lng: 85.04683, crop: "potato", qty_kg: 407.3, ready_hr: 3.6, deadline_hr: 11.33 },
      { lat: 25.53472, lng: 84.95821, crop: "onion", qty_kg: 565.3, ready_hr: 0.45, deadline_hr: 13.94 },
      { lat: 25.84146, lng: 85.10659, crop: "onion", qty_kg: 163.8, ready_hr: 0.4, deadline_hr: 9.97 },
      { lat: 25.19988, lng: 84.5757, crop: "onion", qty_kg: 159.2, ready_hr: 1.68, deadline_hr: 8.3 },
      { lat: 25.80121, lng: 84.74186, crop: "onion", qty_kg: 241.8, ready_hr: 1.67, deadline_hr: 10.02 },
      { lat: 25.86147, lng: 84.70333, crop: "potato", qty_kg: 401.2, ready_hr: 3.8, deadline_hr: 15.31 },
      { lat: 25.28481, lng: 84.86687, crop: "potato", qty_kg: 436.8, ready_hr: 3.75, deadline_hr: 13.61 },
      { lat: 25.38185, lng: 84.709, crop: "onion", qty_kg: 489.9, ready_hr: 0.41, deadline_hr: 13.68 },
      { lat: 25.62767, lng: 84.82135, crop: "potato", qty_kg: 435.6, ready_hr: 2.51, deadline_hr: 11.74 },
      { lat: 25.57947, lng: 85.07169, crop: "potato", qty_kg: 293.2, ready_hr: 1.66, deadline_hr: 12.88 },
      { lat: 25.16801, lng: 84.92366, crop: "potato", qty_kg: 179.9, ready_hr: 3.55, deadline_hr: 16.49 },
      { lat: 25.56552, lng: 84.75026, crop: "onion", qty_kg: 225.7, ready_hr: 0.42, deadline_hr: 9.8 },
      { lat: 25.71629, lng: 84.91422, crop: "onion", qty_kg: 580.4, ready_hr: 1.83, deadline_hr: 15.47 },
    ],
    vehicles: [
      { type_name: "van", count: 2 },
      { type_name: "truck_2t", count: 2 },
      { type_name: "reefer_2t", count: 2 },
      { type_name: "truck_5t", count: 2 },
    ],
    markets: [
      { lat: 25.5603, lng: 84.6632, price: { potato: 11.0 }, capacity_kg: { potato: 1330 } }, // Aarah (Bhojpur), 24 km from farmers | capacity looks like a reporting default: potato 1.33 t on 95% of days
      { lat: 25.33, lng: 84.42, price: { onion: 13.2, potato: 15.9 }, capacity_kg: { onion: 9000, potato: 4500 } }, // Piro (Bhojpur), 57 km from farmers
      { lat: 25.8595, lng: 85.6613, price: { onion: 20.0 }, capacity_kg: { onion: 2000 } }, // Tajpur (Samastipur), 82 km from farmers | capacity looks like a reporting default: onion 2 t on 96% of days
      { lat: 25.23, lng: 84.16, price: { potato: 11.0 }, capacity_kg: { potato: 4000 } }, // Natwar (Rohtas), 85 km from farmers | capacity looks like a reporting default: potato 4 t on 99% of days
      { lat: 25.5612, lng: 83.9813, price: { potato: 14.0 }, capacity_kg: { potato: 5000 } }, // Buxur (Buxar), 92 km from farmers | capacity looks like a reporting default: potato 5 t on 98% of days
      { lat: 26.4234, lng: 85.0412, price: { potato: 11.0 }, capacity_kg: { potato: 60000 } }, // Chakia (Purbi Champaran), 93 km from farmers | capacity looks like a reporting default: potato 60 t on 98% of days
      { lat: 26.5158, lng: 85.2849, price: { onion: 24.0, potato: 22.0 }, capacity_kg: { onion: 2000, potato: 5250 } }, // Sheohar (Sheohar), 109 km from farmers
      { lat: 24.951, lng: 84.0149, price: { onion: 19.0 }, capacity_kg: { onion: 18000 } }, // Sasaram (Rohtas), 115 km from farmers
    ],
  },
};

// ---------- small helpers ----------
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (id, cls) => `<svg class="${cls || "i i-sm"}" aria-hidden="true"><use href="#i-${id}"/></svg>`;
const inr = (n, digits = 0) => (n === undefined || n === null || isNaN(n) ? "\u2013" : "\u20B9" + fmt(n, digits));

// Swap a button into / out of a busy state without losing its label or icon.
function setBusy(btn, busy, busyLabel) {
  if (!btn) return;
  const lbl = btn.querySelector(".lbl") || btn.querySelector("span") || null;
  const use = btn.querySelector("svg use");
  if (busy) {
    btn._saved = { label: lbl ? lbl.textContent : btn.textContent, href: use ? use.getAttribute("href") : null };
    btn.classList.add("is-loading");
    btn.disabled = true;
    if (lbl) lbl.textContent = busyLabel;
    if (use) use.setAttribute("href", "#i-spin");
  } else if (btn._saved) {
    btn.classList.remove("is-loading");
    btn.disabled = false;
    if (lbl) lbl.textContent = btn._saved.label;
    if (use && btn._saved.href) use.setAttribute("href", btn._saved.href);
    btn._saved = null;
  }
}

// ---------- scenario list ----------
// The select-and-blurb UI was replaced by a ruled list: one row per preset,
// counts computed from the preset's own data (nothing invented), one Run
// button that resets, loads, computes and opens the map.
function scenarioMeta(key) {
  const sc = SCENARIOS[key];
  // Labels look like "1. Cold chain: refrigeration-aware pooling", "3. Fleet scarcity + incompatible pickup
  // windows" (no colon) or "Bihar mandis, Mar 2026: potato & onion". Peel the number, then split name from detail.
  const numMatch = sc.label.match(/^(\d+)\.\s*(.*)$/);
  const rest = numMatch ? numMatch[2] : sc.label;
  let name = rest, sub = "";
  const colon = rest.indexOf(":");
  const plus = rest.indexOf(" + ");
  if (colon > -1) { name = rest.slice(0, colon); sub = rest.slice(colon + 1); }
  else if (plus > -1) { name = rest.slice(0, plus); sub = rest.slice(plus + 3); }
  sub = sub.trim();
  sub = sub.charAt(0).toUpperCase() + sub.slice(1);
  return {
    key, name: name.trim(), sub, num: numMatch ? numMatch[1] : null,
    farmers: sc.farmers.length,
    vehicles: sc.vehicles.reduce((n, v) => n + v.count, 0),
    markets: sc.markets.length,
    real: sc.category === "real",
    blurb: sc.blurb || "",
  };
}

function renderScenarioList() {
  const known = new Set(SCENARIO_CATEGORIES.map((c) => c.id));
  const order = [];
  for (const cat of SCENARIO_CATEGORIES) order.push(...Object.keys(SCENARIOS).filter((k) => SCENARIOS[k].category === cat.id));
  order.push(...Object.keys(SCENARIOS).filter((k) => !known.has(SCENARIOS[k].category)));
  $("scenarioList").innerHTML = order.map((key) => {
    const m = scenarioMeta(key);
    const numCell = m.num ? `<div class="sc-num" aria-hidden="true">${m.num}</div>` : `<div class="sc-num is-real" aria-hidden="true">REAL</div>`;
    const tag = m.real
      ? `<span class="tag real" title="Mandi prices and capacities are real; farmers and fleet are synthetic">Real prices</span>`
      : `<span class="tag">Synthetic</span>`;
    return `<article class="sc-row" data-key="${esc(key)}">
      ${numCell}
      <div class="sc-title"><h2>${esc(m.name)}</h2><p>${esc(m.sub)}</p></div>
      <div class="sc-stat"><b>${m.farmers}</b><span>farmers</span></div>
      <div class="sc-stat"><b>${m.vehicles}</b><span>vehicles</span></div>
      <div class="sc-stat"><b>${m.markets}</b><span>markets</span></div>
      <div class="sc-tagcell">${tag}</div>
      <div class="sc-run"><button class="btn btn-primary" type="button" data-run="${esc(key)}">${icon("play")}<span class="lbl run-lbl">Run</span></button></div>
      <details class="sc-more"><summary>${m.real ? "About the data" : "What this tests"}${icon("chevron")}</summary><p>${esc(m.blurb)}</p></details>
    </article>`;
  }).join("");
  refreshRunLabels();
}

function refreshRunLabels() {
  document.querySelectorAll("[data-run] .run-lbl").forEach((el) => {
    el.textContent = state.hasData ? "Replace & run" : "Run";
  });
}

$("scenarioList").addEventListener("click", (e) => {
  const b = e.target.closest("[data-run]");
  if (b && !b.disabled) runScenario(b.dataset.run);
});

async function runScenario(key) {
  const sc = SCENARIOS[key];
  const meta = scenarioMeta(key);
  const status = $("demoStatus");
  const row = document.querySelector(`.sc-row[data-key="${key}"]`);
  const runBtns = [...document.querySelectorAll("[data-run]")];
  const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const say = (t) => { status.className = "status"; status.textContent = t; };

  runBtns.forEach((b) => (b.disabled = true));
  const mine = row && row.querySelector("[data-run]");
  if (mine) setBusy(mine, true, "Running\u2026");
  row && row.classList.add("running");
  try {
    say("Clearing previous data\u2026");
    await api("/reset", { method: "POST" });
    clearPlanViews();
    for (let i = 0; i < sc.farmers.length; i++) {
      if (i % 4 === 0) say(`Loading farmers ${i + 1}\u2013${Math.min(i + 4, sc.farmers.length)} of ${sc.farmers.length}\u2026`);
      await post("/farmers", sc.farmers[i]);
    }
    say("Loading vehicles and markets\u2026");
    for (const v of sc.vehicles) await post("/vehicles", v);
    for (const m of sc.markets) await post("/markets", m);
    await loadAllTables();
    say("Computing the plan\u2026");
    await computePlan();
    say(`${meta.name}: ${meta.farmers} farmers, ${meta.vehicles} vehicles, ${meta.markets} markets. Plan computed.`);
    const mapWasReady = !!(window.FPO.mapview && window.FPO.mapview.initialized);
    showView("map");
    if (mapWasReady) $("mapRefreshBtn").click();
  } catch (err) {
    status.className = "status err";
    status.textContent = err.message;
  } finally {
    if (mine) setBusy(mine, false);
    runBtns.forEach((b) => (b.disabled = false));
    row && row.classList.remove("running");
    refreshRunLabels();
  }
}

// ---------- reset (two-step inline confirm; no browser dialog) ----------
let resetArmTimer = null;
function disarmReset() {
  const btn = $("resetDataBtn");
  clearTimeout(resetArmTimer);
  btn.classList.remove("armed");
  btn.textContent = "Clear all backend data";
}
async function resetAllData() {
  const btn = $("resetDataBtn");
  const status = $("demoStatus");
  if (!btn.classList.contains("armed")) {
    btn.classList.add("armed");
    btn.textContent = "Click again to clear everything";
    clearTimeout(resetArmTimer);
    resetArmTimer = setTimeout(disarmReset, 4000);
    return;
  }
  disarmReset();
  btn.disabled = true;
  status.className = "status";
  status.textContent = "Clearing\u2026";
  try {
    await api("/reset", { method: "POST" });
    await loadAllTables();
    clearPlanViews();
    status.textContent = "Cleared: no farmers, vehicles, markets or plans on the backend.";
  } catch (err) {
    status.className = "status err";
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}
$("resetDataBtn").addEventListener("click", resetAllData);

// The Plan, Comparison and Map views are stale once the data underneath them is gone.
function clearPlanViews() {
  state.lastPlan = null;
  $("planBody").hidden = true;
  $("planEmpty").hidden = false;
  $("planEmpty").innerHTML = "<h2>No plan yet</h2><p>Run a scenario from the Scenarios tab, or compute one from the data you entered.</p>";
  $("compareBody").hidden = true;
  $("compareEmpty").hidden = false;
  $("compareEmpty").innerHTML = "<h2>Nothing to compare yet</h2><p>Run the comparison to see all three approaches side by side on the current data.</p>";
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function fmt(n, digits = 0) {
  if (n === undefined || n === null || isNaN(n)) return "\u2013";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

// ---------- views ----------
function showView(name) {
  if (!$("view-" + name)) name = "start";
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.view === name;
    t.classList.toggle("active", on);
    if (on) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  try { if (location.hash.slice(1) !== name) history.replaceState(null, "", "#" + name); } catch (e) { /* file:// quirks, harmless */ }
  window.scrollTo(0, 0);
  if (name === "map") {
    try { if (window.FPO.ensureMapReady) window.FPO.ensureMapReady(); } catch (e) { console.error(e); }
    requestAnimationFrame(() => { try { if (window.FPO.resizeMap) window.FPO.resizeMap(); } catch (e) {} });
  }
}
window.FPO.showView = showView;

$("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (btn) showView(btn.dataset.view);
});
document.addEventListener("click", (e) => {
  const go = e.target.closest("[data-goto]");
  if (go) showView(go.dataset.goto);
});
window.addEventListener("hashchange", () => showView(location.hash.slice(1) || "start"));

// Side panel on the map view: Story / Details.
function showSidePane(name) {
  document.querySelectorAll("#sideTabs .seg-btn").forEach((b) => {
    const on = b.dataset.side === name;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  $("sidePane-story").hidden = name !== "story";
  $("sidePane-details").hidden = name !== "details";
}
window.FPO.showSidePane = showSidePane;
$("sideTabs").addEventListener("click", (e) => {
  const b = e.target.closest(".seg-btn");
  if (b) showSidePane(b.dataset.side);
});

// ---------- API base + connection chip ----------
function hostOf(url) {
  try { return new URL(url).host; } catch (e) { return url || "Backend"; }
}
function setConn(stateName) {
  $("connDot").dataset.state = stateName;
  const label = stateName === "ok" ? "Connected" : stateName === "bad" ? "Unreachable" : "Backend";
  $("connText").innerHTML = `${label}<span class="conn-host"> \u00B7 ${esc(hostOf(state.apiBase))}</span>`;
  $("connSummary").setAttribute("aria-label", `Backend ${label.toLowerCase()}: ${state.apiBase}`);
}
function loadApiBase() {
  try {
    const saved = localStorage.getItem("fpoApiBase");
    if (saved) state.apiBase = saved;
  } catch (e) { /* storage unavailable, fine */ }
  $("apiBase").value = state.apiBase;
  setConn("unknown");
}
$("saveApi").addEventListener("click", async () => {
  state.apiBase = $("apiBase").value.trim().replace(/\/$/, "");
  try { localStorage.setItem("fpoApiBase", state.apiBase); } catch (e) {}
  $("apiStatus").textContent = "Saved. Checking\u2026";
  setConn("unknown");
  await loadAllTables();
  $("apiStatus").textContent = $("connDot").dataset.state === "ok" ? "Saved and reachable." : "Saved, but nothing answered at that address.";
});

async function api(path, opts) {
  if (!state.apiBase) throw new Error("Set the backend API base URL above first.");
  let res;
  try {
    res = await fetch(state.apiBase + path, opts);
    setConn("ok");
  } catch (e) {
    setConn("bad");
    throw new Error("Could not reach " + state.apiBase + " -- is the backend running? (" + e.message + ")");
  }
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail; } catch (e) {}
    throw new Error(path + " failed (" + res.status + ")" + (detail ? ": " + JSON.stringify(detail) : ""));
  }
  return res.json();
}

// ---------- populate static dropdowns ----------
function populateSelects() {
  const cropSelect = document.querySelector('#farmerForm select[name="crop"]');
  for (const crop of CROPS) {
    const opt = document.createElement("option");
    opt.value = crop;
    opt.textContent = crop;
    cropSelect.appendChild(opt);
  }

  const typeSelect = document.querySelector('#vehicleForm select[name="type_name"]');
  for (const t of VEHICLE_TYPES) {
    const opt = document.createElement("option");
    opt.value = t.name;
    opt.textContent = `${t.name} \u2014 ${t.capacity_kg}kg${t.refrigerated ? ", refrigerated" : ""}, \u20B9${t.fixed_cost}+\u20B9${t.per_km_cost}/km`;
    typeSelect.appendChild(opt);
  }
}

// ---------- farmers ----------
function farmerPayload(form) {
  const data = new FormData(form);
  const refrigRaw = data.get("needs_refrigeration");
  return {
    lat: Number(data.get("lat")),
    lng: Number(data.get("lng")),
    crop: data.get("crop"),
    qty_kg: Number(data.get("qty_kg")),
    ready_hr: Number(data.get("ready_hr")),
    deadline_hr: Number(data.get("deadline_hr")),
    needs_refrigeration: refrigRaw === "" ? null : refrigRaw === "true",
  };
}

document.getElementById("farmerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    await api("/farmers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(farmerPayload(form)),
    });
    form.reset();
    await reloadFarmers();
  } catch (err) {
    alert(err.message);
  }
});

async function reloadFarmers() {
  const tbody = document.querySelector("#farmerTable tbody");
  try {
    const rows = await api("/farmers");
    state.counts.farmers = rows.length;
    tbody.innerHTML = rows.length ? rows.map((f) => `<tr>
      <td>${f.id}</td><td>${fmt(f.lat, 4)}</td><td>${fmt(f.lng, 4)}</td><td>${esc(f.crop)}</td>
      <td class="num">${fmt(f.qty_kg, 1)}</td><td class="num">${fmt(f.ready_hr, 1)} &ndash; ${fmt(f.deadline_hr, 1)}</td>
      <td>${f.needs_refrigeration ? '<span class="tag cold">Cold</span>' : "&ndash;"}</td></tr>`).join("")
      : `<tr><td class="empty-row" colspan="7">No farmers yet. Run a scenario, or use Add farmer.</td></tr>`;
  } catch (e) {
    state.counts.farmers = 0;
    tbody.innerHTML = `<tr><td class="empty-row" colspan="7">Couldn't load farmers. ${esc(e.message)}</td></tr>`;
  }
  updateCounts();
}

// ---------- vehicles ----------
document.getElementById("vehicleForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const data = new FormData(form);
  try {
    await api("/vehicles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type_name: data.get("type_name"),
        count: Number(data.get("count")),
      }),
    });
    form.reset();
    await reloadVehicles();
  } catch (err) {
    alert(err.message);
  }
});

async function reloadVehicles() {
  const tbody = document.querySelector("#vehicleTable tbody");
  try {
    const rows = await api("/vehicles");
    state.counts.vehicles = rows.length;
    tbody.innerHTML = rows.length ? rows.map((v) => `<tr>
      <td>${v.id}</td><td>${esc(v.type_name)}</td><td class="num">${fmt(v.capacity_kg, 1)}</td>
      <td>${v.refrigerated ? '<span class="tag cold">Cold</span>' : "&ndash;"}</td><td class="num">${inr(v.fixed_cost, 2)}</td>
      <td class="num">${inr(v.per_km_cost, 2)}</td></tr>`).join("")
      : `<tr><td class="empty-row" colspan="6">No vehicles yet. Run a scenario, or use Add vehicles.</td></tr>`;
  } catch (e) {
    state.counts.vehicles = 0;
    tbody.innerHTML = `<tr><td class="empty-row" colspan="6">Couldn't load vehicles. ${esc(e.message)}</td></tr>`;
  }
  updateCounts();
}

// ---------- markets ----------
// A market's price/capacity_kg are {crop: value} dicts (a market can quote
// several crops at once), so data entry is a repeatable row of
// (crop, price/kg, capacity kg) rather than one crop per form submit.
function addMarketCropRow() {
  const container = document.getElementById("marketCropRows");
  const row = document.createElement("div");
  row.className = "market-crop-row";
  const cropOptions = CROPS.map((c) => `<option value="${c}">${c}</option>`).join("");
  row.innerHTML = `
    <div><label>Crop</label><select class="mc-crop">${cropOptions}</select></div>
    <div><label>Price (&#8377;/kg)</label><input class="mc-price" type="number" min="0" step="0.1"></div>
    <div><label>Capacity (kg)</label><input class="mc-capacity" type="number" min="0" step="0.1"></div>
    <button type="button" class="remove-row" title="Remove crop" aria-label="Remove crop"><svg class="i i-sm" aria-hidden="true"><use href="#i-close"/></svg></button>`;
  row.querySelector(".remove-row").addEventListener("click", () => row.remove());
  container.appendChild(row);
}
document.getElementById("addMarketCropRow").addEventListener("click", addMarketCropRow);
addMarketCropRow(); // start with one row

document.getElementById("submitMarket").addEventListener("click", async () => {
  const form = document.getElementById("marketForm");
  const lat = form.elements["lat"].value;
  const lng = form.elements["lng"].value;
  const status = document.getElementById("marketStatus");

  if (lat === "" || lng === "") {
    alert("Enter the market's latitude and longitude.");
    return;
  }

  const price = {};
  const capacity_kg = {};
  const rows = document.querySelectorAll("#marketCropRows .market-crop-row");
  for (const row of rows) {
    const crop = row.querySelector(".mc-crop").value;
    const priceVal = row.querySelector(".mc-price").value;
    const capVal = row.querySelector(".mc-capacity").value;
    if (priceVal === "" || capVal === "") continue; // skip incomplete rows
    price[crop] = Number(priceVal);
    capacity_kg[crop] = Number(capVal);
  }
  if (Object.keys(price).length === 0) {
    alert("Add at least one crop with a price and capacity.");
    return;
  }

  try {
    await api("/markets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: Number(lat), lng: Number(lng), price, capacity_kg }),
    });
    form.reset();
    document.getElementById("marketCropRows").innerHTML = "";
    addMarketCropRow();
    status.textContent = "Added.";
    setTimeout(() => (status.textContent = ""), 2000);
    await reloadMarkets();
  } catch (err) {
    alert(err.message);
  }
});

async function reloadMarkets() {
  const tbody = document.querySelector("#marketTable tbody");
  try {
    const rows = await api("/markets");
    state.counts.markets = rows.length;
    tbody.innerHTML = rows.length ? rows.map((m) => {
      const crops = Object.keys(m.price)
        .map((c) => `${esc(c)} (\u20B9${fmt(m.price[c], 2)}, ${fmt(m.capacity_kg[c] ?? 0, 1)} kg)`)
        .join(", ");
      return `<tr><td>${m.id}</td><td>${fmt(m.lat, 4)}</td><td>${fmt(m.lng, 4)}</td><td style="white-space:normal">${crops}</td></tr>`;
    }).join("")
      : `<tr><td class="empty-row" colspan="4">No markets yet. Run a scenario, or use Add market.</td></tr>`;
  } catch (e) {
    state.counts.markets = 0;
    tbody.innerHTML = `<tr><td class="empty-row" colspan="4">Couldn't load markets. ${esc(e.message)}</td></tr>`;
  }
  updateCounts();
}


// ---------- data summary (header chip + tab counts) ----------
state.counts = { farmers: 0, vehicles: 0, markets: 0 };
state.hasData = false;
function updateCounts() {
  const c = state.counts;
  $("farmerCount").textContent = c.farmers;
  $("vehicleCount").textContent = c.vehicles;
  $("marketCount").textContent = c.markets;
  state.hasData = c.farmers + c.vehicles + c.markets > 0;
  $("dataSummary").textContent = state.hasData
    ? `Loaded: ${c.farmers} farmers, ${c.vehicles} vehicles, ${c.markets} markets.`
    : "No data loaded on the backend.";
  refreshRunLabels();
}
function loadAllTables() {
  return Promise.all([reloadFarmers(), reloadVehicles(), reloadMarkets()]).then(updateCounts);
}

// ---------- compute plan ----------
async function computePlan() {
  const data = await api("/plan/compute", { method: "POST" });
  state.lastPlan = data;
  if (typeof window.FPO.onPlanComputed === "function") {
    try { window.FPO.onPlanComputed(data); } catch (e) { console.error(e); }
  }
  // Independent try/catches: a problem in one view must not blank the other.
  try { renderDashboard(data); } catch (err) { showViewError("planEmpty", "planBody", "Couldn't render the plan", err.message); }
  try { renderComparison(data); } catch (err) { showViewError("compareEmpty", "compareBody", "Couldn't render the comparison", err.message); }
  return data;
}

function showViewError(emptyId, bodyId, title, message) {
  $(bodyId).hidden = true;
  const box = $(emptyId);
  box.hidden = false;
  box.innerHTML = `<h2 class="bad-text">${esc(title)}</h2><p>${esc(message)}</p>`;
}

async function runCompute(triggerBtn) {
  const btn = $(triggerBtn);
  setBusy(btn, true, "Computing\u2026");
  try {
    await computePlan();
  } catch (err) {
    showViewError("planEmpty", "planBody", "Couldn't compute a plan", err.message);
    showViewError("compareEmpty", "compareBody", "Couldn't compute a plan", err.message);
  } finally {
    setBusy(btn, false);
  }
}
$("computeBtn").addEventListener("click", () => runCompute("computeBtn"));
$("compareBtn").addEventListener("click", () => runCompute("compareBtn"));

// ---------- plan view ----------
function line(label, value, cls) {
  return `<div class="line ${cls || ""}"><dt>${label}</dt><dd>${value}</dd></div>`;
}

function renderDashboard(data) {
  const ilo = data.integrated_logistics_optimization;
  const s = ilo.summary || {};
  const total = s.total_qty_kg || 0;
  const pctOf = (kg) => (total > 0 ? Math.max(0, (kg || 0) / total * 100) : 0);
  const unsold = s.total_unsold_kg || 0, noTruck = s.total_unserved_no_vehicle_kg || 0, withheld = s.total_withheld_kg || 0;
  const hasFg = s.farmgate_revenue !== undefined;
  const meta = data.realistic_baselines?.ilo_meta;
  const fellBack = !!(meta && meta.chosen && meta.chosen.startsWith("fallback:"));
  const missed = unsold + noTruck + withheld;
  const soldPct = Math.max(0, 100 - pctOf(missed));

  // Revenue - transport = net holds for this algorithm; only draw it as arithmetic when it does.
  const adds = s.total_revenue !== undefined && s.total_transport_cost !== undefined
    && Math.abs(s.total_revenue - s.total_transport_cost - s.net_return) < 1;
  const ret = adds
    ? line("Revenue", inr(s.total_revenue)) + line("Less transport cost", "\u2212" + inr(s.total_transport_cost))
    : line("Revenue", inr(s.total_revenue)) + line("Transport cost", inr(s.total_transport_cost));

  const harvest =
    `<dl>` + line("Harvest collected", `${fmt(total, 1)} kg`) + line("Sold at a market", `${fmt(soldPct, 1)}%`) + `</dl>` +
    `<div class="harvest-bar" role="img" aria-label="${fmt(soldPct, 1)}% of the harvest sold">` +
      `<i class="seg-sold" style="width:${soldPct}%"></i>` +
      (unsold ? `<i class="seg-unsold" style="width:${pctOf(unsold)}%"></i>` : "") +
      (noTruck ? `<i class="seg-notruck" style="width:${pctOf(noTruck)}%"></i>` : "") +
      (withheld ? `<i class="seg-withheld" style="width:${pctOf(withheld)}%"></i>` : "") +
    `</div><dl>` +
    (unsold ? line(`<span class="key unsold"></span>Unsold at market`, `${fmt(unsold, 1)} kg`) : "") +
    (noTruck ? line(`<span class="key notruck"></span>Never got a truck`, `<span class="bad-text">${fmt(noTruck, 1)} kg</span>`) : "") +
    (withheld ? line(`<span class="key withheld"></span>${hasFg ? "Not hauled: sold at the farm gate" : "Withheld as unprofitable"}`, `${fmt(withheld, 1)} kg`) : "") +
    line("Spoilage in transit", `${fmt(s.total_spoilage_kg, 1)} kg`, "sub") +
    line("Pools formed", fmt(s.pools_formed), "sub") +
    line("Vehicles used", fmt(s.vehicles_used) + (s.vehicle_utilization_pct !== undefined ? ` (${fmt(s.vehicle_utilization_pct, 0)}% utilised)` : ""), "sub") + `</dl>`;

  $("dashSummary").innerHTML =
    `<div><h2>Return</h2><dl>${ret}${line("Net return", inr(s.net_return), "total")}${line("Per farmer", inr(s.net_return_per_farmer), "sub")}` +
      (hasFg ? line("Produce not hauled, at the assumed farm-gate price", inr(s.farmgate_revenue), "sub") + line("Farmer value (net return + farm gate)", inr(s.net_return_incl_farmgate), "total") : "") + `</dl></div>` +
    `<div><h2>Harvest</h2>${harvest}</div>`;

  $("dashCoverageNote").className = missed > 0.05 || fellBack ? "note warn" : "note";
  const coverageText = missed > 0.05
    ? (hasFg
      ? `${fmt(100 - soldPct, 1)}% of the harvest (${fmt(missed, 1)} kg) was not sold at a market. Produce the plan did not haul is valued at the assumed farm-gate price (${fmt((s.farmgate_discount || 0) * 100, 0)}% below the median mandi price), which is an assumption, not data. Read net return and coverage together.`
      : `${fmt(100 - soldPct, 1)}% of the harvest (${fmt(missed, 1)} kg) never reached a paying market. A high net return with low coverage means the plan is leaving produce behind, so read the two together.`)
    : "";
  const fallbackText = fellBack
    ? `ILO found no set of trips that beats a simpler plan under these prices, so it recommends that plan instead (${meta.chosen.replace("fallback:", "").replace(/_/g, " ")}). On this scenario the pooling logic adds nothing; try a lower farm-gate price or nearer mandis.`
    : "";
  $("dashCoverageNote").innerHTML = (missed > 0.05 || fellBack)
    ? `${icon("alert", "i")}<span>${[fallbackText, coverageText].filter(Boolean).join(" ")}</span>`
    : "";

  const pools = ilo.pools || [];
  $("poolCount").textContent = pools.length;
  const th = (t, num) => `<th${num ? ' class="num"' : ""}>${t}</th>`;
  const rows = pools.map((p, i) => {
    const veh = p.sold_at_farmgate ? `<span class="tag warn">Sold at the farm gate</span>` : p.withheld ? `<span class="tag warn">Withheld: unprofitable</span>` : p.spot_hire ? `Hired truck` : `Vehicle ${p.vehicle_id}` + (p.infeasible ? ` <span class="tag bad">Infeasible</span>` : "");
    const mk = (p.markets_used || []).map((m) => `<span class="tag">Market ${m}</span>`).join(" ") || "\u2013";
    const bad = (v) => (v > 0 ? ` class="num bad-text"` : ` class="num"`);
    return `<tr>
      <td class="pool-id" data-label="Pool">${i + 1}</td>
      <td data-label="Vehicle">${veh}</td>
      <td class="num" data-label="Farmers">${(p.farmer_ids || []).length}</td>
      <td class="num" data-label="Load">${fmt(p.total_qty_kg, 1)} kg</td>
      <td class="num" data-label="Revenue">${inr(p.revenue)}</td>
      <td class="num" data-label="Transport">${inr(p.transport_cost)}</td>
      <td class="num net" data-label="Net return">${inr(p.net_return)}</td>
      <td class="num" data-label="Spoiled">${fmt(p.spoilage_loss_kg, 1)} kg</td>
      <td${bad(p.unsold_kg)} data-label="Unsold">${fmt(p.unsold_kg, 1)} kg</td>
      <td${bad(p.unserved_no_vehicle_kg)} data-label="No truck">${fmt(p.unserved_no_vehicle_kg, 1)} kg</td>
      <td data-label="Markets">${mk}</td>
    </tr>`;
  }).join("");
  $("poolCards").innerHTML = pools.length
    ? `<table class="data ledger stack"><thead><tr>${th("Pool")}${th("Vehicle")}${th("Farmers", 1)}${th("Load", 1)}${th("Revenue", 1)}${th("Transport", 1)}${th("Net return", 1)}${th("Spoiled", 1)}${th("Unsold", 1)}${th("No truck", 1)}${th("Markets")}</tr></thead><tbody>${rows}</tbody></table>`
    : `<p class="hint">No pools in this plan.</p>`;

  $("planEmpty").hidden = true;
  $("planBody").hidden = false;
}

// ---------- comparison view ----------
const ALGO_BLURB = {
  integrated_logistics_optimization: "Hauls only what beats selling at the farm gate. Merges farmers heading to the same mandi into full trucks, respects refrigeration and pickup windows, picks the best set of trips with an exact solver, and splits produce across markets so overflow reroutes to the next-best one.",
  proximity_pooling: "Up to 4 neighbours within 5 km share one hired truck to the nearest mandi, if it is within reach and clearly beats the trader's offer. No profit check, no refrigeration or window planning, no rerouting.",
  individual_transport: "Each farmer hires a truck to the nearest mandi, if it is within reach and clearly beats the trader's offer; otherwise sells at the farm gate. No profit check, no pooling.",
};
const ALGO_NAME = {
  integrated_logistics_optimization: "ILO (ours)",
  proximity_pooling: "Proximity Pooling",
  individual_transport: "Individual Transport",
};

function renderComparison(data) {
  const sum = (k) => data[k]?.summary || {};
  const ilo = sum(KEYS[0]);
  // The baselines let farmers sell at the farm gate, which a plain "net return" would score as zero, so the
  // headline is net return PLUS farm-gate sales whenever the API provides it (older stored plans fall back).
  const hasFg = KEYS.every((k) => sum(k).net_return_incl_farmgate !== undefined);
  const valueOf = (s) => (hasFg ? s.net_return_incl_farmgate : s.net_return) || 0;
  const maxNet = Math.max(1, ...KEYS.map((k) => valueOf(sum(k))));

  const head = `<div class="sb-head"><span>Approach</span><span>${hasFg ? "Farmer value (\u20B9)" : "Net return (\u20B9)"}</span><span>${hasFg ? "Sold at a market (%)" : "Produce sold (%)"}</span><span style="text-align:right">ILO vs this</span></div>`;
  const rows = KEYS.map((k) => {
    const s = sum(k);
    const net = valueOf(s);
    const w = Math.max(0, net) / maxNet * 100;
    const pct = s.pct_qty_served ?? 0;
    const isIlo = k === KEYS[0];
    let delta = `<span class="sb-delta">\u2013<small>reference</small></span>`;
    if (!isIlo) {
      const diff = valueOf(ilo) - net;
      const rel = net !== 0 ? diff / Math.abs(net) * 100 : null;
      const cls = diff > 0.5 ? "up" : diff < -0.5 ? "down" : "";
      const word = diff > 0.5 ? "more" : diff < -0.5 ? "less" : "same";
      delta = `<span class="sb-delta ${cls}">${diff > 0.5 ? "+" : diff < -0.5 ? "\u2212" : ""}${inr(Math.abs(diff))}<small>${word === "same" ? (hasFg ? "equal value" : "equal net return") : `ILO ${hasFg ? "earns" : "nets"} ${word}` + (rel !== null ? ` (${fmt(Math.abs(rel), 0)}%)` : "")}</small></span>`;
    }
    return `<div class="sb-row ${isIlo ? "is-ilo" : ""}">
      <div class="sb-name"><h2>${ALGO_NAME[k]}</h2><p>${ALGO_BLURB[k]}</p></div>
      <div class="sb-col"><div class="sb-cap">${hasFg ? "Farmer value" : "Net return"}</div><div class="bar-cell"><div class="bar-track"><div class="bar-fill ${net < 0 ? "neg" : ""}" style="width:${w}%"></div></div><span class="bar-val">${inr(net)}</span></div></div>
      <div class="sb-col"><div class="sb-cap">${hasFg ? "Sold at a market" : "Produce sold"}</div><div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, pct)}%"></div></div><span class="bar-val">${fmt(pct, 1)}%</span></div></div>
      ${delta}
    </div>`;
  }).join("");
  $("scoreboard").innerHTML = head + rows;

  const metrics = [
    { label: "Revenue", key: "total_revenue", fmt: (v) => inr(v), best: "max" },
    { label: "Transport cost", key: "total_transport_cost", fmt: (v) => inr(v), best: "min" },
    { label: "Net return (hauled trips)", key: "net_return", fmt: (v) => inr(v), best: "max" },
    { label: "Value of produce not hauled, at the assumed farm-gate price", key: "farmgate_revenue", fmt: (v) => inr(v), best: null },
    { label: "Farmer value (net return + farm-gate sales)", key: "net_return_incl_farmgate", fmt: (v) => inr(v), best: "max" },
    { label: "Farmer value per farmer", key: "net_return_per_farmer_incl_farmgate", fmt: (v) => inr(v), best: "max" },
    { label: "Net return per farmer (hauled only)", key: "net_return_per_farmer", fmt: (v) => inr(v), best: "max" },
    { label: "Produce sold at a market", key: "pct_qty_served", fmt: (v) => fmt(v, 1) + "%", best: "max" },
    { label: "Produce not hauled (sold at the farm gate)", key: "farmgate_kg", fmt: (v) => fmt(v, 1) + " kg", best: null },
    { label: "Spoilage in transit", key: "total_spoilage_kg", fmt: (v) => fmt(v, 1) + " kg", best: "min" },
    { label: "Unsold at market", key: "total_unsold_kg", fmt: (v) => fmt(v, 1) + " kg", best: "min" },
    { label: "Never got a truck", key: "total_unserved_no_vehicle_kg", fmt: (v) => fmt(v, 1) + " kg", best: "min" },
    { label: "Vehicles used", key: "vehicles_used", fmt: (v) => fmt(v), best: null },
    { label: "Pools formed", key: "pools_formed", fmt: (v) => fmt(v), best: null },
  ].filter((m) => KEYS.some((k) => sum(k)[m.key] !== undefined));
  const trs = metrics.map((m) => {
    const vals = KEYS.map((k) => sum(k)[m.key]);
    const nums = vals.filter((v) => typeof v === "number");
    const target = m.best === "max" ? Math.max(...nums) : m.best === "min" ? Math.min(...nums) : null;
    const allSame = nums.every((v) => Math.abs(v - nums[0]) < 1e-9);
    return `<tr><td>${m.label}</td>${vals.map((v) => `<td${target !== null && !allSame && v === target ? ' class="best"' : ""}>${v === undefined ? "\u2013" : m.fmt(v)}</td>`).join("")}</tr>`;
  }).join("");
  const beh = data.realistic_baselines?.assumptions?.behaviour;
  const disc = ilo.farmgate_discount;
  const fgNote = hasFg
    ? `<p class="hint"><b>Assumptions, not data.</b> Produce a plan does not haul is valued at the farm-gate price, taken as ${disc !== undefined ? fmt(disc * 100, 0) + "%" : "a fixed share"} below the median mandi price. ILO and both baselines are costed the same way (the empty return leg is paid and spoilage counts from pickup), so the comparison is like-for-like. Individual Transport and Proximity Pooling model farmers who haul by simple rules${beh ? ` (mandi within ${fmt(beh.max_haul_km, 0)} km and at least ${fmt(beh.price_margin * 100, 0)}% above the trader's offer)` : ""}, hire spot trucks${beh ? ` at a ${fmt((beh.spot_markup - 1) * 100, 0)}% markup with a ${fmt(beh.spot_lead_hr, 1)} h wait` : ""}, and do not calculate profit, so some of their trips lose money.</p>`
    : "";
  $("compareTable").innerHTML = `<table class="data"><thead><tr><th>Measure</th>${KEYS.map((k) => `<th>${ALGO_NAME[k]}</th>`).join("")}</tr></thead><tbody>${trs}</tbody></table>
    <p class="hint">Highlighted cell = best value in that row. Vehicles used and pools formed describe how a plan is built, not how good it is, so they're never highlighted.</p>${fgNote}`;

  $("compareEmpty").hidden = true;
  $("compareBody").hidden = false;
}

// ---------- init ----------
populateSelects();
renderScenarioList();
loadApiBase();
clearPlanViews();
updateCounts();
loadAllTables();
showView(location.hash.slice(1) || "start");
