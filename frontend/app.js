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
  karnataka_bengaluru: {
    category: "real",
    label: "Karnataka mandis around Bengaluru, Feb-Apr 2026: tomato, onion, potato, cauliflower, mango",
    blurb: "REAL: 8 Karnataka mandis (Binny Mill (F&V), Bengaluru, Bengaluru, Doddaballapur, Ramanagara, Kanakapura, Channapatna, Chickkaballapura, Kolar) with prices and daily arrivals from Agmarknet via India Data Portal, 2026-02-01 to 2026-04-30 (median of days; mandi coordinates are the portal's own). Cleaned before use: 79 rows dropped (prices outside min/max or 3x off the series median, arrival typos above 20x the median, non-positive prices); 0 mandi-crop series with implausible units (e.g. bundle prices labelled per quintal) dropped; mandis without coordinates (0) or with suspect ones (0) left out, and 9 mandi-crop series absorbing under 1 t/day removed (too small to be a market for a pickup round). Capacity is the median reported daily arrival, a proxy and not a limit: 0 of 21 mandi-crop series here repeat one value on 70%+ of days, and 0 of those were raised to the state's lower-quartile arrival for that crop, which is an assumption. SYNTHETIC: 61 farmers (onion 18, tomato 17, potato 16, mango 7, cauliflower 3) in villages within 18 km of (12.96, 77.54) and a 16-vehicle fleet; no public farmer or fleet data exists. Counts are assumptions: about 60 pickups per collection round (shared across crops by local volume, never more than 30% of a crop's daily absorption by these mandis), lots 150-600 kg, fleet capacity 39 t = 1.5x the day's 23.9 t of produce. The farm-gate price used in the comparison is an assumption too.",
    farmers: [
      { lat: 13.01396, lng: 77.56528, crop: "tomato", qty_kg: 397.5, ready_hr: 0.03, deadline_hr: 11.25 },
      { lat: 13.07294, lng: 77.62451, crop: "onion", qty_kg: 492.9, ready_hr: 0.1, deadline_hr: 11.0 },
      { lat: 13.10856, lng: 77.55767, crop: "tomato", qty_kg: 523.4, ready_hr: 0.1, deadline_hr: 8.0 },
      { lat: 12.95, lng: 77.58873, crop: "potato", qty_kg: 267.1, ready_hr: 0.12, deadline_hr: 11.73 },
      { lat: 13.02698, lng: 77.68405, crop: "cauliflower", qty_kg: 229.3, ready_hr: 0.24, deadline_hr: 9.19 },
      { lat: 13.0524, lng: 77.63748, crop: "mango", qty_kg: 392.4, ready_hr: 0.26, deadline_hr: 9.57 },
      { lat: 12.93524, lng: 77.56312, crop: "cauliflower", qty_kg: 290.0, ready_hr: 0.27, deadline_hr: 7.36 },
      { lat: 13.09224, lng: 77.53587, crop: "tomato", qty_kg: 245.6, ready_hr: 0.3, deadline_hr: 13.62 },
      { lat: 12.97032, lng: 77.53882, crop: "onion", qty_kg: 324.6, ready_hr: 0.35, deadline_hr: 9.83 },
      { lat: 13.01269, lng: 77.52015, crop: "tomato", qty_kg: 569.7, ready_hr: 0.35, deadline_hr: 12.13 },
      { lat: 13.12483, lng: 77.53308, crop: "potato", qty_kg: 377.6, ready_hr: 0.46, deadline_hr: 12.53 },
      { lat: 13.07031, lng: 77.6306, crop: "onion", qty_kg: 382.4, ready_hr: 0.59, deadline_hr: 12.38 },
      { lat: 13.05365, lng: 77.64016, crop: "potato", qty_kg: 474.9, ready_hr: 0.82, deadline_hr: 13.37 },
      { lat: 13.10492, lng: 77.5541, crop: "onion", qty_kg: 528.1, ready_hr: 0.82, deadline_hr: 14.74 },
      { lat: 12.97053, lng: 77.5671, crop: "tomato", qty_kg: 210.5, ready_hr: 0.84, deadline_hr: 9.65 },
      { lat: 13.01589, lng: 77.47423, crop: "tomato", qty_kg: 327.4, ready_hr: 0.84, deadline_hr: 13.68 },
      { lat: 12.96813, lng: 77.58828, crop: "potato", qty_kg: 467.1, ready_hr: 0.95, deadline_hr: 9.01 },
      { lat: 12.94185, lng: 77.59271, crop: "potato", qty_kg: 435.4, ready_hr: 1.0, deadline_hr: 13.43 },
      { lat: 12.92653, lng: 77.51736, crop: "tomato", qty_kg: 309.4, ready_hr: 1.12, deadline_hr: 12.32 },
      { lat: 12.94014, lng: 77.52921, crop: "tomato", qty_kg: 475.6, ready_hr: 1.14, deadline_hr: 9.09 },
      { lat: 12.90251, lng: 77.52931, crop: "potato", qty_kg: 565.2, ready_hr: 1.26, deadline_hr: 9.01 },
      { lat: 13.02789, lng: 77.68359, crop: "onion", qty_kg: 570.4, ready_hr: 1.32, deadline_hr: 12.87 },
      { lat: 12.95738, lng: 77.54833, crop: "onion", qty_kg: 564.8, ready_hr: 1.48, deadline_hr: 12.32 },
      { lat: 12.93589, lng: 77.52346, crop: "potato", qty_kg: 245.8, ready_hr: 1.68, deadline_hr: 9.84 },
      { lat: 12.92664, lng: 77.47391, crop: "onion", qty_kg: 517.1, ready_hr: 1.73, deadline_hr: 14.94 },
      { lat: 13.01243, lng: 77.54504, crop: "cauliflower", qty_kg: 154.3, ready_hr: 1.77, deadline_hr: 12.65 },
      { lat: 13.05296, lng: 77.68245, crop: "onion", qty_kg: 494.1, ready_hr: 1.85, deadline_hr: 10.46 },
      { lat: 12.94152, lng: 77.52292, crop: "potato", qty_kg: 566.6, ready_hr: 1.89, deadline_hr: 14.53 },
      { lat: 12.91259, lng: 77.57377, crop: "tomato", qty_kg: 408.6, ready_hr: 1.93, deadline_hr: 14.87 },
      { lat: 13.05607, lng: 77.58332, crop: "mango", qty_kg: 166.7, ready_hr: 2.02, deadline_hr: 10.76 },
      { lat: 12.9406, lng: 77.57582, crop: "potato", qty_kg: 262.7, ready_hr: 2.04, deadline_hr: 9.62 },
      { lat: 12.94844, lng: 77.53972, crop: "tomato", qty_kg: 489.2, ready_hr: 2.07, deadline_hr: 10.81 },
      { lat: 13.11754, lng: 77.52499, crop: "tomato", qty_kg: 407.8, ready_hr: 2.1, deadline_hr: 9.7 },
      { lat: 13.06099, lng: 77.64458, crop: "mango", qty_kg: 221.9, ready_hr: 2.12, deadline_hr: 9.75 },
      { lat: 13.0794, lng: 77.63686, crop: "onion", qty_kg: 169.8, ready_hr: 2.15, deadline_hr: 15.49 },
      { lat: 13.02988, lng: 77.67968, crop: "onion", qty_kg: 414.0, ready_hr: 2.17, deadline_hr: 9.26 },
      { lat: 12.93377, lng: 77.57376, crop: "potato", qty_kg: 424.0, ready_hr: 2.33, deadline_hr: 8.97 },
      { lat: 12.97011, lng: 77.54476, crop: "potato", qty_kg: 259.4, ready_hr: 2.33, deadline_hr: 13.14 },
      { lat: 12.92988, lng: 77.58032, crop: "onion", qty_kg: 156.0, ready_hr: 2.4, deadline_hr: 14.01 },
      { lat: 12.93016, lng: 77.46583, crop: "onion", qty_kg: 509.5, ready_hr: 2.51, deadline_hr: 9.28 },
      { lat: 12.99221, lng: 77.54856, crop: "mango", qty_kg: 513.3, ready_hr: 2.62, deadline_hr: 16.29 },
      { lat: 12.93782, lng: 77.53789, crop: "tomato", qty_kg: 384.2, ready_hr: 2.79, deadline_hr: 13.7 },
      { lat: 13.03211, lng: 77.66449, crop: "onion", qty_kg: 489.8, ready_hr: 2.86, deadline_hr: 13.14 },
      { lat: 12.94365, lng: 77.57751, crop: "potato", qty_kg: 163.4, ready_hr: 3.0, deadline_hr: 13.81 },
      { lat: 13.01389, lng: 77.66405, crop: "tomato", qty_kg: 347.7, ready_hr: 3.03, deadline_hr: 13.5 },
      { lat: 12.94636, lng: 77.58001, crop: "potato", qty_kg: 447.1, ready_hr: 3.12, deadline_hr: 13.01 },
      { lat: 12.93404, lng: 77.47976, crop: "onion", qty_kg: 285.8, ready_hr: 3.19, deadline_hr: 10.0 },
      { lat: 13.04609, lng: 77.45479, crop: "onion", qty_kg: 467.1, ready_hr: 3.21, deadline_hr: 16.09 },
      { lat: 12.99767, lng: 77.67126, crop: "onion", qty_kg: 266.2, ready_hr: 3.22, deadline_hr: 16.51 },
      { lat: 13.06982, lng: 77.60521, crop: "mango", qty_kg: 262.3, ready_hr: 3.27, deadline_hr: 10.79 },
      { lat: 12.92414, lng: 77.45743, crop: "tomato", qty_kg: 431.1, ready_hr: 3.37, deadline_hr: 11.93 },
      { lat: 12.93882, lng: 77.46919, crop: "tomato", qty_kg: 343.0, ready_hr: 3.47, deadline_hr: 9.75 },
      { lat: 13.04726, lng: 77.56338, crop: "mango", qty_kg: 337.7, ready_hr: 3.48, deadline_hr: 15.81 },
      { lat: 12.94089, lng: 77.49855, crop: "tomato", qty_kg: 421.6, ready_hr: 3.53, deadline_hr: 12.9 },
      { lat: 12.90175, lng: 77.54257, crop: "potato", qty_kg: 591.2, ready_hr: 3.56, deadline_hr: 14.82 },
      { lat: 12.89916, lng: 77.52448, crop: "onion", qty_kg: 545.9, ready_hr: 3.59, deadline_hr: 15.14 },
      { lat: 13.00647, lng: 77.44735, crop: "onion", qty_kg: 481.7, ready_hr: 3.6, deadline_hr: 15.23 },
      { lat: 12.90146, lng: 77.54627, crop: "potato", qty_kg: 265.4, ready_hr: 3.63, deadline_hr: 15.0 },
      { lat: 12.90843, lng: 77.53, crop: "potato", qty_kg: 363.7, ready_hr: 3.69, deadline_hr: 12.55 },
      { lat: 13.05585, lng: 77.63728, crop: "tomato", qty_kg: 589.7, ready_hr: 3.72, deadline_hr: 10.73 },
      { lat: 13.03369, lng: 77.69525, crop: "mango", qty_kg: 589.8, ready_hr: 3.92, deadline_hr: 14.22 },
    ],
    vehicles: [
      { type_name: "truck_5t", count: 2 },
      { type_name: "truck_2t", count: 4 },
      { type_name: "van", count: 3 },
      { type_name: "reefer_5t", count: 2 },
      { type_name: "reefer_2t", count: 3 },
      { type_name: "reefer_van", count: 2 },
    ],
    markets: [
      { lat: 12.96496, lng: 77.56221, price: { cauliflower: 20.0, mango: 33.33, tomato: 16.0 }, capacity_kg: { cauliflower: 8250, mango: 55000, tomato: 42750 } }, // Binny Mill (F&V), Bengaluru (Bengaluru Urban), 3 km from farmer centre
      { lat: 13.02137, lng: 77.54433, price: { onion: 10.5, potato: 12.5 }, capacity_kg: { onion: 652000, potato: 498900 } }, // Bengaluru (Bengaluru Urban), 6 km from farmer centre
      { lat: 13.31124, lng: 77.53886, price: { onion: 17.0, potato: 17.0, tomato: 13.0 }, capacity_kg: { onion: 2000, potato: 1400, tomato: 1500 } }, // Doddaballapur (Bengaluru Rural), 39 km from farmer centre
      { lat: 12.7162, lng: 77.2743, price: { cauliflower: 20.0, mango: 48.67, tomato: 12.25 }, capacity_kg: { cauliflower: 1600, mango: 7500, tomato: 9400 } }, // Ramanagara (Bengaluru South), 40 km from farmer centre
      { lat: 12.55303, lng: 77.40725, price: { tomato: 12.0 }, capacity_kg: { tomato: 1100 } }, // Kanakapura (Bengaluru South), 48 km from farmer centre
      { lat: 12.6581, lng: 77.212, price: { mango: 54.17, tomato: 12.5 }, capacity_kg: { mango: 37750, tomato: 4800 } }, // Channapatna (Bengaluru South), 49 km from farmer centre
      { lat: 13.43912, lng: 77.71937, price: { cauliflower: 9.0, onion: 16.5, potato: 10.0, tomato: 11.82 }, capacity_kg: { cauliflower: 1200, onion: 4000, potato: 16500, tomato: 21800 } }, // Chickkaballapura (Chikkaballapura), 56 km from farmer centre
      { lat: 13.12426, lng: 78.11122, price: { cauliflower: 11.0, potato: 11.0, tomato: 6.6 }, capacity_kg: { cauliflower: 9400, potato: 3000, tomato: 528100 } }, // Kolar (Kolar), 64 km from farmer centre
    ],
  },
  up_aligarh: {
    category: "real",
    label: "Uttar Pradesh mandis around Aligarh, Nov 2025 - Jan 2026: potato, onion, tomato, cauliflower, spinach",
    blurb: "REAL: 8 Uttar Pradesh mandis (Aligarh, Atrauli, Khair, Charra, Haathras, Sikarpur, Khurja, Sikandraraau) with prices and daily arrivals from Agmarknet via India Data Portal, 2025-11-01 to 2026-01-31 (median of days; mandi coordinates are the portal's own). Cleaned before use: 51 rows dropped (prices outside min/max or 3x off the series median, arrival typos above 20x the median, non-positive prices); 1 mandi-crop series with implausible units (e.g. bundle prices labelled per quintal) dropped; mandis without coordinates (0) or with suspect ones (0) left out, and 36 mandi-crop series absorbing under 1 t/day removed (too small to be a market for a pickup round). Capacity is the median reported daily arrival, a proxy and not a limit: 1 of 26 mandi-crop series here repeat one value on 70%+ of days, and 1 of those were raised to the state's lower-quartile arrival for that crop, which is an assumption. SYNTHETIC: 59 farmers (potato 31, onion 9, tomato 7, cauliflower 7, spinach 5) in villages within 18 km of (27.95, 78.11) and a 15-vehicle fleet; no public farmer or fleet data exists. Counts are assumptions: about 60 pickups per collection round (shared across crops by local volume, never more than 30% of a crop's daily absorption by these mandis), lots 150-600 kg, fleet capacity 33 t = 1.5x the day's 23.5 t of produce. The farm-gate price used in the comparison is an assumption too.",
    farmers: [
      { lat: 27.86591, lng: 77.96086, crop: "potato", qty_kg: 262.3, ready_hr: 0.03, deadline_hr: 6.94 },
      { lat: 28.05204, lng: 77.96608, crop: "onion", qty_kg: 559.9, ready_hr: 0.09, deadline_hr: 9.0 },
      { lat: 28.00729, lng: 78.01147, crop: "onion", qty_kg: 151.7, ready_hr: 0.11, deadline_hr: 6.33 },
      { lat: 28.0655, lng: 77.98037, crop: "potato", qty_kg: 297.9, ready_hr: 0.17, deadline_hr: 10.47 },
      { lat: 27.89084, lng: 78.18779, crop: "tomato", qty_kg: 562.6, ready_hr: 0.29, deadline_hr: 9.07 },
      { lat: 27.88323, lng: 78.17897, crop: "spinach", qty_kg: 308.9, ready_hr: 0.39, deadline_hr: 8.89 },
      { lat: 27.93331, lng: 78.15721, crop: "tomato", qty_kg: 251.0, ready_hr: 0.39, deadline_hr: 14.1 },
      { lat: 27.83977, lng: 77.95317, crop: "potato", qty_kg: 427.8, ready_hr: 0.43, deadline_hr: 7.92 },
      { lat: 28.03086, lng: 77.98444, crop: "potato", qty_kg: 372.6, ready_hr: 0.54, deadline_hr: 9.97 },
      { lat: 27.96507, lng: 78.25041, crop: "potato", qty_kg: 362.3, ready_hr: 0.8, deadline_hr: 7.27 },
      { lat: 28.00984, lng: 78.02004, crop: "potato", qty_kg: 529.8, ready_hr: 0.83, deadline_hr: 7.7 },
      { lat: 28.04913, lng: 78.22483, crop: "potato", qty_kg: 563.5, ready_hr: 0.88, deadline_hr: 10.89 },
      { lat: 27.79546, lng: 78.13668, crop: "cauliflower", qty_kg: 238.3, ready_hr: 0.93, deadline_hr: 12.04 },
      { lat: 27.87161, lng: 78.18769, crop: "potato", qty_kg: 189.2, ready_hr: 0.97, deadline_hr: 11.82 },
      { lat: 27.94997, lng: 78.1223, crop: "tomato", qty_kg: 167.6, ready_hr: 1.03, deadline_hr: 10.48 },
      { lat: 27.86566, lng: 78.19297, crop: "spinach", qty_kg: 576.0, ready_hr: 1.05, deadline_hr: 14.21 },
      { lat: 27.79404, lng: 78.13773, crop: "spinach", qty_kg: 574.8, ready_hr: 1.11, deadline_hr: 11.23 },
      { lat: 28.06439, lng: 77.98947, crop: "potato", qty_kg: 452.4, ready_hr: 1.17, deadline_hr: 9.49 },
      { lat: 27.86531, lng: 78.16568, crop: "potato", qty_kg: 565.6, ready_hr: 1.19, deadline_hr: 11.99 },
      { lat: 27.86107, lng: 78.17228, crop: "cauliflower", qty_kg: 221.3, ready_hr: 1.23, deadline_hr: 8.2 },
      { lat: 27.84564, lng: 78.1864, crop: "potato", qty_kg: 375.0, ready_hr: 1.29, deadline_hr: 10.18 },
      { lat: 27.85998, lng: 77.96274, crop: "potato", qty_kg: 458.9, ready_hr: 1.33, deadline_hr: 13.1 },
      { lat: 27.96831, lng: 78.25412, crop: "potato", qty_kg: 307.5, ready_hr: 1.47, deadline_hr: 14.97 },
      { lat: 28.06025, lng: 77.9983, crop: "potato", qty_kg: 196.4, ready_hr: 1.47, deadline_hr: 14.21 },
      { lat: 27.96061, lng: 78.25053, crop: "potato", qty_kg: 425.6, ready_hr: 1.54, deadline_hr: 8.56 },
      { lat: 28.0591, lng: 78.20596, crop: "potato", qty_kg: 542.9, ready_hr: 1.56, deadline_hr: 14.73 },
      { lat: 28.00834, lng: 78.01692, crop: "onion", qty_kg: 196.1, ready_hr: 1.67, deadline_hr: 13.57 },
      { lat: 27.85293, lng: 78.04236, crop: "potato", qty_kg: 463.6, ready_hr: 1.82, deadline_hr: 14.67 },
      { lat: 27.85936, lng: 78.19798, crop: "potato", qty_kg: 243.0, ready_hr: 1.9, deadline_hr: 13.96 },
      { lat: 27.96265, lng: 78.15113, crop: "onion", qty_kg: 478.9, ready_hr: 1.93, deadline_hr: 14.54 },
      { lat: 27.95919, lng: 78.14497, crop: "cauliflower", qty_kg: 190.8, ready_hr: 1.94, deadline_hr: 10.43 },
      { lat: 28.04829, lng: 77.98353, crop: "tomato", qty_kg: 349.7, ready_hr: 1.95, deadline_hr: 9.39 },
      { lat: 27.87079, lng: 78.20819, crop: "potato", qty_kg: 573.0, ready_hr: 1.97, deadline_hr: 14.49 },
      { lat: 27.96358, lng: 78.24477, crop: "cauliflower", qty_kg: 311.6, ready_hr: 1.98, deadline_hr: 11.18 },
      { lat: 27.85424, lng: 78.18325, crop: "tomato", qty_kg: 420.9, ready_hr: 1.99, deadline_hr: 13.8 },
      { lat: 27.88534, lng: 78.0956, crop: "onion", qty_kg: 467.7, ready_hr: 2.0, deadline_hr: 11.68 },
      { lat: 27.89204, lng: 78.09128, crop: "spinach", qty_kg: 465.3, ready_hr: 2.14, deadline_hr: 11.29 },
      { lat: 27.95321, lng: 78.08115, crop: "potato", qty_kg: 231.9, ready_hr: 2.2, deadline_hr: 14.33 },
      { lat: 27.89011, lng: 78.10024, crop: "onion", qty_kg: 591.0, ready_hr: 2.23, deadline_hr: 13.33 },
      { lat: 27.79486, lng: 78.10002, crop: "cauliflower", qty_kg: 230.7, ready_hr: 2.31, deadline_hr: 11.69 },
      { lat: 27.96124, lng: 78.16405, crop: "onion", qty_kg: 409.7, ready_hr: 2.38, deadline_hr: 11.41 },
      { lat: 27.9927, lng: 78.02605, crop: "potato", qty_kg: 471.4, ready_hr: 2.46, deadline_hr: 11.31 },
      { lat: 27.78714, lng: 78.11852, crop: "onion", qty_kg: 510.3, ready_hr: 2.61, deadline_hr: 12.65 },
      { lat: 28.04551, lng: 78.21556, crop: "potato", qty_kg: 508.2, ready_hr: 2.63, deadline_hr: 11.66 },
      { lat: 27.87072, lng: 78.19303, crop: "potato", qty_kg: 488.2, ready_hr: 2.86, deadline_hr: 10.77 },
      { lat: 27.97868, lng: 78.14708, crop: "potato", qty_kg: 536.5, ready_hr: 3.08, deadline_hr: 11.57 },
      { lat: 27.84198, lng: 78.18076, crop: "onion", qty_kg: 384.6, ready_hr: 3.17, deadline_hr: 12.69 },
      { lat: 27.85975, lng: 77.95753, crop: "cauliflower", qty_kg: 237.9, ready_hr: 3.24, deadline_hr: 10.82 },
      { lat: 28.03732, lng: 78.23174, crop: "potato", qty_kg: 437.7, ready_hr: 3.33, deadline_hr: 11.16 },
      { lat: 27.94214, lng: 78.16884, crop: "tomato", qty_kg: 551.7, ready_hr: 3.41, deadline_hr: 9.64 },
      { lat: 27.89755, lng: 78.1926, crop: "spinach", qty_kg: 509.0, ready_hr: 3.62, deadline_hr: 16.8 },
      { lat: 27.84222, lng: 77.9403, crop: "potato", qty_kg: 510.6, ready_hr: 3.66, deadline_hr: 11.1 },
      { lat: 27.994, lng: 78.02724, crop: "potato", qty_kg: 215.7, ready_hr: 3.73, deadline_hr: 11.56 },
      { lat: 28.07007, lng: 77.96623, crop: "potato", qty_kg: 419.2, ready_hr: 3.77, deadline_hr: 10.34 },
      { lat: 27.93398, lng: 78.12933, crop: "potato", qty_kg: 486.0, ready_hr: 3.84, deadline_hr: 17.44 },
      { lat: 27.94449, lng: 78.14298, crop: "cauliflower", qty_kg: 356.3, ready_hr: 3.84, deadline_hr: 17.33 },
      { lat: 27.94348, lng: 78.09113, crop: "potato", qty_kg: 385.2, ready_hr: 3.88, deadline_hr: 10.31 },
      { lat: 28.06457, lng: 77.98551, crop: "tomato", qty_kg: 599.3, ready_hr: 3.94, deadline_hr: 13.96 },
      { lat: 28.02986, lng: 78.2289, crop: "potato", qty_kg: 368.2, ready_hr: 3.96, deadline_hr: 11.52 },
    ],
    vehicles: [
      { type_name: "truck_5t", count: 2 },
      { type_name: "truck_2t", count: 4 },
      { type_name: "van", count: 4 },
      { type_name: "reefer_5t", count: 1 },
      { type_name: "reefer_2t", count: 2 },
      { type_name: "reefer_van", count: 2 },
    ],
    markets: [
      { lat: 27.87318, lng: 78.10356, price: { cauliflower: 19.0, onion: 11.7, potato: 8.55, spinach: 9.75, tomato: 28.0 }, capacity_kg: { cauliflower: 65000, onion: 90000, potato: 350000, spinach: 55000, tomato: 50000 } }, // Aligarh (Aligarh), 8 km from farmer centre
      { lat: 28.03655, lng: 78.27724, price: { cauliflower: 17.0, potato: 8.5 }, capacity_kg: { cauliflower: 1300, potato: 10000 } }, // Atrauli (Aligarh), 19 km from farmer centre
      { lat: 27.94537, lng: 77.83331, price: { cauliflower: 12.0, onion: 14.0, potato: 7.0, tomato: 34.0 }, capacity_kg: { cauliflower: 2000, onion: 2000, potato: 24500, tomato: 2000 } }, // Khair (Aligarh), 28 km from farmer centre
      { lat: 27.93241, lng: 78.39534, price: { onion: 16.5, potato: 12.5 }, capacity_kg: { onion: 2775, potato: 2000 } }, // Charra (Aligarh), 28 km from farmer centre | onion capacity raised from 1 t (reported on 98% of days) to the state lower quartile
      { lat: 27.61087, lng: 78.0558, price: { cauliflower: 20.05, onion: 12.5, potato: 8.5, tomato: 27.6 }, capacity_kg: { cauliflower: 38000, onion: 48500, potato: 1500000, tomato: 45000 } }, // Haathras (Hathras), 38 km from farmer centre
      { lat: 28.2806, lng: 78.00362, price: { cauliflower: 14.0, onion: 11.0, potato: 9.0 }, capacity_kg: { cauliflower: 2200, onion: 2000, potato: 81000 } }, // Sikarpur (Bulandshahr), 39 km from farmer centre
      { lat: 28.22909, lng: 77.87081, price: { cauliflower: 15.0, onion: 12.8, potato: 11.5, spinach: 10.5, tomato: 29.0 }, capacity_kg: { cauliflower: 6500, onion: 25000, potato: 50000, spinach: 3500, tomato: 9000 } }, // Khurja (Bulandshahr), 40 km from farmer centre
      { lat: 27.68126, lng: 78.40187, price: { potato: 5.5 }, capacity_kg: { potato: 25000 } }, // Sikandraraau (Hathras), 41 km from farmer centre
    ],
  },
  maharashtra_junnar: {
    category: "real",
    label: "Maharashtra mandis around Junnar (Pune), Feb-Apr 2026: onion, tomato, potato, cauliflower, spinach",
    blurb: "REAL: 8 Maharashtra mandis (Junnar(Narayangaon), Manchar, Junnar(Alephata), Junnar(Otur), Khed, Khed(Chakan), Pune(Moshi), Parner) with prices and daily arrivals from Agmarknet via India Data Portal, 2026-02-01 to 2026-04-30 (median of days; mandi coordinates are the portal's own). Cleaned before use: 34 rows dropped (prices outside min/max or 3x off the series median, arrival typos above 20x the median, non-positive prices); 13 mandi-crop series with implausible units (e.g. bundle prices labelled per quintal) dropped; mandis without coordinates (5) or with suspect ones (0) left out, and 12 mandi-crop series absorbing under 1 t/day removed (too small to be a market for a pickup round). Capacity is the median reported daily arrival, a proxy and not a limit: 0 of 22 mandi-crop series here repeat one value on 70%+ of days, and 0 of those were raised to the state's lower-quartile arrival for that crop, which is an assumption. SYNTHETIC: 60 farmers (onion 34, tomato 10, cauliflower 8, potato 8) in villages within 18 km of (19.05, 73.98) and a 14-vehicle fleet; no public farmer or fleet data exists. Counts are assumptions: about 60 pickups per collection round (shared across crops by local volume, never more than 30% of a crop's daily absorption by these mandis), lots 150-600 kg, fleet capacity 32 t = 1.5x the day's 21.9 t of produce. The farm-gate price used in the comparison is an assumption too.",
    farmers: [
      { lat: 19.03875, lng: 74.05831, crop: "onion", qty_kg: 307.3, ready_hr: 0.17, deadline_hr: 12.09 },
      { lat: 19.08362, lng: 74.00985, crop: "onion", qty_kg: 519.1, ready_hr: 0.21, deadline_hr: 12.44 },
      { lat: 18.93117, lng: 74.03446, crop: "tomato", qty_kg: 396.2, ready_hr: 0.22, deadline_hr: 6.63 },
      { lat: 19.14477, lng: 74.06539, crop: "onion", qty_kg: 438.8, ready_hr: 0.23, deadline_hr: 11.11 },
      { lat: 18.92816, lng: 73.91494, crop: "onion", qty_kg: 251.5, ready_hr: 0.45, deadline_hr: 7.0 },
      { lat: 19.07852, lng: 73.91699, crop: "onion", qty_kg: 470.6, ready_hr: 0.5, deadline_hr: 10.42 },
      { lat: 18.93297, lng: 73.91306, crop: "onion", qty_kg: 598.6, ready_hr: 0.6, deadline_hr: 11.59 },
      { lat: 19.12951, lng: 74.09959, crop: "onion", qty_kg: 157.0, ready_hr: 0.67, deadline_hr: 10.86 },
      { lat: 19.03193, lng: 74.03685, crop: "onion", qty_kg: 196.3, ready_hr: 0.71, deadline_hr: 11.43 },
      { lat: 19.0509, lng: 73.99558, crop: "onion", qty_kg: 545.6, ready_hr: 0.77, deadline_hr: 8.4 },
      { lat: 19.0673, lng: 73.99486, crop: "onion", qty_kg: 489.3, ready_hr: 0.82, deadline_hr: 9.97 },
      { lat: 19.05154, lng: 73.97178, crop: "tomato", qty_kg: 509.5, ready_hr: 0.83, deadline_hr: 9.84 },
      { lat: 18.9224, lng: 73.90013, crop: "onion", qty_kg: 299.4, ready_hr: 1.04, deadline_hr: 14.53 },
      { lat: 18.92255, lng: 74.03046, crop: "cauliflower", qty_kg: 241.7, ready_hr: 1.15, deadline_hr: 9.96 },
      { lat: 19.18168, lng: 73.93322, crop: "cauliflower", qty_kg: 219.8, ready_hr: 1.28, deadline_hr: 11.76 },
      { lat: 18.95571, lng: 73.8965, crop: "cauliflower", qty_kg: 477.5, ready_hr: 1.44, deadline_hr: 10.17 },
      { lat: 18.93098, lng: 74.0007, crop: "onion", qty_kg: 516.6, ready_hr: 1.52, deadline_hr: 11.52 },
      { lat: 19.02822, lng: 73.90069, crop: "onion", qty_kg: 177.6, ready_hr: 1.56, deadline_hr: 11.78 },
      { lat: 18.99615, lng: 74.02965, crop: "onion", qty_kg: 562.2, ready_hr: 1.57, deadline_hr: 11.61 },
      { lat: 19.09593, lng: 73.9024, crop: "onion", qty_kg: 260.1, ready_hr: 1.69, deadline_hr: 9.94 },
      { lat: 19.09005, lng: 74.00012, crop: "onion", qty_kg: 571.1, ready_hr: 1.79, deadline_hr: 11.89 },
      { lat: 19.10493, lng: 73.89384, crop: "onion", qty_kg: 339.6, ready_hr: 1.79, deadline_hr: 8.9 },
      { lat: 18.92721, lng: 73.89611, crop: "tomato", qty_kg: 423.6, ready_hr: 1.95, deadline_hr: 9.9 },
      { lat: 19.04524, lng: 73.98331, crop: "tomato", qty_kg: 413.4, ready_hr: 1.96, deadline_hr: 12.63 },
      { lat: 18.93542, lng: 74.02335, crop: "tomato", qty_kg: 155.7, ready_hr: 2.04, deadline_hr: 10.99 },
      { lat: 19.01891, lng: 74.02005, crop: "tomato", qty_kg: 276.2, ready_hr: 2.11, deadline_hr: 11.15 },
      { lat: 18.98014, lng: 74.00636, crop: "tomato", qty_kg: 284.8, ready_hr: 2.13, deadline_hr: 15.83 },
      { lat: 19.001, lng: 73.99759, crop: "onion", qty_kg: 517.8, ready_hr: 2.21, deadline_hr: 13.16 },
      { lat: 18.92662, lng: 73.99974, crop: "onion", qty_kg: 399.8, ready_hr: 2.23, deadline_hr: 9.74 },
      { lat: 19.06917, lng: 74.04488, crop: "onion", qty_kg: 502.4, ready_hr: 2.23, deadline_hr: 11.76 },
      { lat: 19.19384, lng: 73.94741, crop: "onion", qty_kg: 433.5, ready_hr: 2.25, deadline_hr: 15.8 },
      { lat: 19.12724, lng: 74.0942, crop: "onion", qty_kg: 464.6, ready_hr: 2.26, deadline_hr: 15.77 },
      { lat: 19.15105, lng: 74.06942, crop: "potato", qty_kg: 524.9, ready_hr: 2.49, deadline_hr: 14.22 },
      { lat: 18.94546, lng: 74.03123, crop: "onion", qty_kg: 257.8, ready_hr: 2.56, deadline_hr: 9.47 },
      { lat: 19.0817, lng: 74.05428, crop: "cauliflower", qty_kg: 387.0, ready_hr: 2.58, deadline_hr: 9.59 },
      { lat: 18.99185, lng: 74.02287, crop: "onion", qty_kg: 469.0, ready_hr: 2.64, deadline_hr: 14.24 },
      { lat: 18.94629, lng: 74.00825, crop: "cauliflower", qty_kg: 190.4, ready_hr: 2.73, deadline_hr: 16.18 },
      { lat: 19.07536, lng: 73.99424, crop: "onion", qty_kg: 532.1, ready_hr: 2.74, deadline_hr: 10.8 },
      { lat: 18.9636, lng: 73.90586, crop: "potato", qty_kg: 409.0, ready_hr: 2.82, deadline_hr: 12.18 },
      { lat: 18.99953, lng: 74.01185, crop: "onion", qty_kg: 256.9, ready_hr: 2.82, deadline_hr: 12.79 },
      { lat: 19.00673, lng: 74.00565, crop: "potato", qty_kg: 193.6, ready_hr: 2.86, deadline_hr: 14.08 },
      { lat: 18.97072, lng: 73.89643, crop: "potato", qty_kg: 450.0, ready_hr: 2.87, deadline_hr: 16.36 },
      { lat: 18.92775, lng: 73.88501, crop: "potato", qty_kg: 450.2, ready_hr: 2.88, deadline_hr: 13.61 },
      { lat: 19.15848, lng: 74.07214, crop: "onion", qty_kg: 174.9, ready_hr: 2.9, deadline_hr: 14.54 },
      { lat: 19.13173, lng: 74.06369, crop: "onion", qty_kg: 445.2, ready_hr: 3.0, deadline_hr: 16.65 },
      { lat: 18.99576, lng: 74.01368, crop: "tomato", qty_kg: 419.9, ready_hr: 3.03, deadline_hr: 9.07 },
      { lat: 19.03238, lng: 74.07628, crop: "potato", qty_kg: 367.8, ready_hr: 3.05, deadline_hr: 11.14 },
      { lat: 18.96168, lng: 73.91722, crop: "tomato", qty_kg: 569.3, ready_hr: 3.06, deadline_hr: 11.46 },
      { lat: 19.08759, lng: 73.99972, crop: "onion", qty_kg: 471.3, ready_hr: 3.07, deadline_hr: 15.72 },
      { lat: 19.04255, lng: 73.97771, crop: "tomato", qty_kg: 295.2, ready_hr: 3.21, deadline_hr: 16.36 },
      { lat: 19.10247, lng: 73.90978, crop: "onion", qty_kg: 248.2, ready_hr: 3.29, deadline_hr: 11.72 },
      { lat: 19.04524, lng: 73.97969, crop: "onion", qty_kg: 241.0, ready_hr: 3.32, deadline_hr: 15.16 },
      { lat: 19.06209, lng: 73.88908, crop: "cauliflower", qty_kg: 214.5, ready_hr: 3.45, deadline_hr: 16.17 },
      { lat: 19.00286, lng: 74.0407, crop: "potato", qty_kg: 177.4, ready_hr: 3.58, deadline_hr: 11.58 },
      { lat: 19.0126, lng: 74.03886, crop: "onion", qty_kg: 158.7, ready_hr: 3.62, deadline_hr: 12.52 },
      { lat: 18.907, lng: 74.01331, crop: "cauliflower", qty_kg: 443.8, ready_hr: 3.63, deadline_hr: 14.49 },
      { lat: 19.03943, lng: 73.98585, crop: "onion", qty_kg: 330.1, ready_hr: 3.65, deadline_hr: 10.29 },
      { lat: 19.00825, lng: 74.04093, crop: "onion", qty_kg: 243.5, ready_hr: 3.87, deadline_hr: 17.34 },
      { lat: 18.92103, lng: 74.01661, crop: "potato", qty_kg: 222.0, ready_hr: 3.97, deadline_hr: 11.45 },
      { lat: 19.1541, lng: 74.08683, crop: "cauliflower", qty_kg: 362.1, ready_hr: 3.98, deadline_hr: 12.13 },
    ],
    vehicles: [
      { type_name: "truck_5t", count: 2 },
      { type_name: "truck_2t", count: 4 },
      { type_name: "van", count: 4 },
      { type_name: "reefer_5t", count: 1 },
      { type_name: "reefer_2t", count: 2 },
      { type_name: "reefer_van", count: 1 },
    ],
    markets: [
      { lat: 19.10743, lng: 73.97275, price: { cauliflower: 7.0, onion: 8.0, potato: 8.0, tomato: 10.0 }, capacity_kg: { cauliflower: 34500, onion: 4800, potato: 10300, tomato: 254500 } }, // Junnar(Narayangaon) (Pune), 6 km from farmer centre
      { lat: 19.00219, lng: 73.94635, price: { cauliflower: 9.5, onion: 12.6, potato: 9.55 }, capacity_kg: { cauliflower: 91300, onion: 1354600, potato: 14950 } }, // Manchar (Pune), 7 km from farmer centre
      { lat: 19.18206, lng: 74.13102, price: { onion: 11.25 }, capacity_kg: { onion: 429150 } }, // Junnar(Alephata) (Pune), 22 km from farmer centre
      { lat: 19.2621, lng: 73.97798, price: { cauliflower: 10.0, onion: 10.5, potato: 10.0 }, capacity_kg: { cauliflower: 38300, onion: 955400, potato: 20350 } }, // Junnar(Otur) (Pune), 23 km from farmer centre
      { lat: 18.84057, lng: 73.90722, price: { cauliflower: 9.0 }, capacity_kg: { cauliflower: 7400 } }, // Khed (Pune), 25 km from farmer centre
      { lat: 18.76539, lng: 73.86651, price: { cauliflower: 10.0, onion: 12.0, potato: 10.0, tomato: 12.0 }, capacity_kg: { cauliflower: 19250, onion: 25000, potato: 100000, tomato: 29400 } }, // Khed(Chakan) (Pune), 34 km from farmer centre
      { lat: 18.66307, lng: 73.84738, price: { cauliflower: 9.5, mango: 100.0, onion: 8.0, potato: 9.5, tomato: 9.0 }, capacity_kg: { cauliflower: 33200, mango: 2000, onion: 68000, potato: 85600, tomato: 63750 } }, // Pune(Moshi) (Pune), 46 km from farmer centre
      { lat: 18.99974, lng: 74.44059, price: { onion: 9.5 }, capacity_kg: { onion: 977300 } }, // Parner (Ahilyanagar), 49 km from farmer centre
    ],
  },
  mp_indore: {
    category: "real",
    label: "Madhya Pradesh mandis around Indore, Feb-Apr 2026: onion, potato, tomato, cauliflower",
    blurb: "REAL: 11 Madhya Pradesh mandis (Dewas(F&V), Ujjain, Indore, Badnawar, Shajapur(F&V), Shajapur, Kalapipal, Ashta, Sarangpur, Ratlam, Dhamnod(F&V)) with prices and daily arrivals from Agmarknet via India Data Portal, 2026-02-01 to 2026-04-30 (median of days; mandi coordinates are the portal's own). Cleaned before use: 47 rows dropped (prices outside min/max or 3x off the series median, arrival typos above 20x the median, non-positive prices); 0 mandi-crop series with implausible units (e.g. bundle prices labelled per quintal) dropped; mandis without coordinates (27) or with suspect ones (0) left out, and 23 mandi-crop series absorbing under 1 t/day removed (too small to be a market for a pickup round). Capacity is the median reported daily arrival, a proxy and not a limit: 0 of 21 mandi-crop series here repeat one value on 70%+ of days, and 0 of those were raised to the state's lower-quartile arrival for that crop, which is an assumption. SYNTHETIC: 57 farmers (onion 30, potato 27) in villages within 18 km of (22.97, 75.87) and a 13-vehicle fleet; no public farmer or fleet data exists. Counts are assumptions: about 60 pickups per collection round (shared across crops by local volume, never more than 30% of a crop's daily absorption by these mandis), lots 150-600 kg, fleet capacity 30 t = 1.5x the day's 20.6 t of produce. The farm-gate price used in the comparison is an assumption too.",
    farmers: [
      { lat: 22.96584, lng: 75.8261, crop: "potato", qty_kg: 598.4, ready_hr: 0.0, deadline_hr: 7.89 },
      { lat: 23.07017, lng: 75.94005, crop: "onion", qty_kg: 283.5, ready_hr: 0.16, deadline_hr: 13.6 },
      { lat: 23.12989, lng: 75.80966, crop: "onion", qty_kg: 592.8, ready_hr: 0.18, deadline_hr: 13.27 },
      { lat: 22.82947, lng: 75.78893, crop: "potato", qty_kg: 424.4, ready_hr: 0.2, deadline_hr: 9.89 },
      { lat: 23.12987, lng: 75.82742, crop: "potato", qty_kg: 197.9, ready_hr: 0.2, deadline_hr: 11.83 },
      { lat: 22.91153, lng: 75.91998, crop: "onion", qty_kg: 567.8, ready_hr: 0.22, deadline_hr: 7.91 },
      { lat: 22.97122, lng: 75.84488, crop: "potato", qty_kg: 163.7, ready_hr: 0.22, deadline_hr: 8.68 },
      { lat: 23.08276, lng: 75.95147, crop: "potato", qty_kg: 432.1, ready_hr: 0.27, deadline_hr: 10.12 },
      { lat: 22.84904, lng: 75.86436, crop: "onion", qty_kg: 520.1, ready_hr: 0.31, deadline_hr: 12.87 },
      { lat: 22.95528, lng: 75.84332, crop: "potato", qty_kg: 309.5, ready_hr: 0.4, deadline_hr: 10.68 },
      { lat: 22.85055, lng: 75.77905, crop: "potato", qty_kg: 599.6, ready_hr: 0.53, deadline_hr: 8.2 },
      { lat: 22.8507, lng: 75.91243, crop: "onion", qty_kg: 399.9, ready_hr: 0.53, deadline_hr: 9.07 },
      { lat: 22.89094, lng: 75.81121, crop: "potato", qty_kg: 476.4, ready_hr: 0.59, deadline_hr: 7.76 },
      { lat: 22.93692, lng: 75.95888, crop: "onion", qty_kg: 244.5, ready_hr: 0.6, deadline_hr: 12.45 },
      { lat: 22.8506, lng: 75.88374, crop: "onion", qty_kg: 235.0, ready_hr: 0.64, deadline_hr: 8.66 },
      { lat: 22.97828, lng: 75.84288, crop: "potato", qty_kg: 253.5, ready_hr: 0.8, deadline_hr: 13.78 },
      { lat: 23.11541, lng: 75.79748, crop: "potato", qty_kg: 484.9, ready_hr: 0.9, deadline_hr: 11.9 },
      { lat: 23.01596, lng: 75.99778, crop: "onion", qty_kg: 154.6, ready_hr: 0.94, deadline_hr: 12.86 },
      { lat: 23.12214, lng: 75.81168, crop: "onion", qty_kg: 300.0, ready_hr: 0.96, deadline_hr: 8.04 },
      { lat: 22.86869, lng: 75.80024, crop: "potato", qty_kg: 196.8, ready_hr: 0.98, deadline_hr: 11.07 },
      { lat: 23.0572, lng: 75.9359, crop: "potato", qty_kg: 324.6, ready_hr: 1.02, deadline_hr: 7.3 },
      { lat: 22.95082, lng: 75.76476, crop: "onion", qty_kg: 285.2, ready_hr: 1.09, deadline_hr: 13.55 },
      { lat: 22.9593, lng: 76.04204, crop: "potato", qty_kg: 571.3, ready_hr: 1.13, deadline_hr: 10.0 },
      { lat: 22.94867, lng: 75.84071, crop: "onion", qty_kg: 205.9, ready_hr: 1.23, deadline_hr: 12.34 },
      { lat: 22.98268, lng: 75.98212, crop: "onion", qty_kg: 393.5, ready_hr: 1.28, deadline_hr: 13.97 },
      { lat: 22.87114, lng: 75.77813, crop: "potato", qty_kg: 554.5, ready_hr: 1.44, deadline_hr: 10.15 },
      { lat: 22.92915, lng: 75.97311, crop: "potato", qty_kg: 399.1, ready_hr: 1.55, deadline_hr: 14.83 },
      { lat: 22.94957, lng: 76.0369, crop: "potato", qty_kg: 417.5, ready_hr: 1.55, deadline_hr: 8.45 },
      { lat: 22.85436, lng: 75.8784, crop: "onion", qty_kg: 364.2, ready_hr: 1.61, deadline_hr: 12.45 },
      { lat: 22.89758, lng: 75.89793, crop: "onion", qty_kg: 239.8, ready_hr: 1.68, deadline_hr: 7.92 },
      { lat: 23.03501, lng: 75.98947, crop: "onion", qty_kg: 376.0, ready_hr: 1.68, deadline_hr: 15.25 },
      { lat: 23.13145, lng: 75.82311, crop: "potato", qty_kg: 591.2, ready_hr: 1.71, deadline_hr: 14.7 },
      { lat: 23.00562, lng: 75.98969, crop: "onion", qty_kg: 521.4, ready_hr: 1.77, deadline_hr: 11.01 },
      { lat: 23.02077, lng: 75.97974, crop: "onion", qty_kg: 305.6, ready_hr: 1.78, deadline_hr: 15.27 },
      { lat: 23.04764, lng: 75.95183, crop: "potato", qty_kg: 387.7, ready_hr: 1.98, deadline_hr: 10.35 },
      { lat: 22.95982, lng: 76.06675, crop: "onion", qty_kg: 463.5, ready_hr: 2.17, deadline_hr: 10.57 },
      { lat: 22.86497, lng: 75.89675, crop: "onion", qty_kg: 162.6, ready_hr: 2.23, deadline_hr: 13.63 },
      { lat: 22.92455, lng: 75.76891, crop: "onion", qty_kg: 467.6, ready_hr: 2.27, deadline_hr: 10.39 },
      { lat: 22.93729, lng: 75.9716, crop: "onion", qty_kg: 533.3, ready_hr: 2.28, deadline_hr: 8.9 },
      { lat: 23.06176, lng: 75.93466, crop: "potato", qty_kg: 362.8, ready_hr: 2.41, deadline_hr: 14.45 },
      { lat: 22.85945, lng: 75.81927, crop: "potato", qty_kg: 300.9, ready_hr: 2.54, deadline_hr: 12.71 },
      { lat: 22.88827, lng: 75.80432, crop: "potato", qty_kg: 343.2, ready_hr: 2.57, deadline_hr: 14.76 },
      { lat: 22.94853, lng: 76.06141, crop: "onion", qty_kg: 264.5, ready_hr: 2.61, deadline_hr: 12.71 },
      { lat: 22.83013, lng: 75.87541, crop: "onion", qty_kg: 366.5, ready_hr: 2.96, deadline_hr: 16.56 },
      { lat: 22.94864, lng: 75.94344, crop: "potato", qty_kg: 522.5, ready_hr: 3.04, deadline_hr: 10.6 },
      { lat: 23.01131, lng: 76.00391, crop: "onion", qty_kg: 289.9, ready_hr: 3.07, deadline_hr: 10.8 },
      { lat: 23.12818, lng: 75.80913, crop: "potato", qty_kg: 466.4, ready_hr: 3.29, deadline_hr: 13.92 },
      { lat: 22.85659, lng: 75.87165, crop: "onion", qty_kg: 186.3, ready_hr: 3.32, deadline_hr: 15.28 },
      { lat: 22.91256, lng: 75.97771, crop: "potato", qty_kg: 177.9, ready_hr: 3.46, deadline_hr: 14.9 },
      { lat: 22.85912, lng: 75.81186, crop: "potato", qty_kg: 281.1, ready_hr: 3.67, deadline_hr: 15.76 },
      { lat: 23.04, lng: 76.00104, crop: "onion", qty_kg: 158.3, ready_hr: 3.69, deadline_hr: 15.5 },
      { lat: 23.10961, lng: 75.80234, crop: "onion", qty_kg: 174.5, ready_hr: 3.72, deadline_hr: 13.02 },
      { lat: 22.83865, lng: 75.89654, crop: "onion", qty_kg: 268.6, ready_hr: 3.76, deadline_hr: 12.17 },
      { lat: 22.91621, lng: 75.75294, crop: "onion", qty_kg: 490.8, ready_hr: 3.77, deadline_hr: 13.83 },
      { lat: 22.93205, lng: 76.03977, crop: "potato", qty_kg: 414.6, ready_hr: 3.93, deadline_hr: 11.48 },
      { lat: 22.97458, lng: 75.84704, crop: "onion", qty_kg: 204.8, ready_hr: 3.94, deadline_hr: 16.46 },
      { lat: 22.92488, lng: 75.92847, crop: "potato", qty_kg: 303.0, ready_hr: 4.0, deadline_hr: 13.07 },
    ],
    vehicles: [
      { type_name: "truck_5t", count: 3 },
      { type_name: "truck_2t", count: 5 },
      { type_name: "van", count: 5 },
    ],
    markets: [
      { lat: 22.974, lng: 76.0666, price: { cauliflower: 13.7, onion: 7.25, potato: 8.0, tomato: 8.25 }, capacity_kg: { cauliflower: 1200, onion: 3200, potato: 2800, tomato: 1500 } }, // Dewas(F&V) (Dewas), 20 km from farmer centre
      { lat: 23.1954, lng: 75.7804, price: { onion: 11.85, potato: 6.0 }, capacity_kg: { onion: 35640, potato: 148670 } }, // Ujjain (Ujjain), 26 km from farmer centre
      { lat: 22.7085, lng: 75.8708, price: { onion: 11.17, potato: 8.36 }, capacity_kg: { onion: 325310, potato: 153340 } }, // Indore (Indore), 30 km from farmer centre
      { lat: 23.01675, lng: 75.23599, price: { onion: 5.0 }, capacity_kg: { onion: 37565 } }, // Badnawar (Dhar), 65 km from farmer centre
      { lat: 23.3942, lng: 76.31741, price: { onion: 6.0, potato: 5.25 }, capacity_kg: { onion: 538050, potato: 437550 } }, // Shajapur(F&V) (Shajapur), 65 km from farmer centre
      { lat: 23.431, lng: 76.298, price: { onion: 8.73, potato: 5.98 }, capacity_kg: { onion: 89770, potato: 152260 } }, // Shajapur (Shajapur), 67 km from farmer centre
      { lat: 23.2031, lng: 76.5011, price: { onion: 9.33 }, capacity_kg: { onion: 8420 } }, // Kalapipal (Shajapur), 69 km from farmer centre
      { lat: 23.0, lng: 76.72, price: { onion: 11.0 }, capacity_kg: { onion: 2530 } }, // Ashta (Sehore), 87 km from farmer centre
      { lat: 23.57, lng: 76.47, price: { onion: 4.22 }, capacity_kg: { onion: 18600 } }, // Sarangpur (Rajgarh), 90 km from farmer centre
      { lat: 23.3093, lng: 75.03985, price: { onion: 11.02 }, capacity_kg: { onion: 34980 } }, // Ratlam (Ratlam), 93 km from farmer centre
      { lat: 22.218, lng: 75.471, price: { cauliflower: 11.0, onion: 12.0, potato: 8.0, tomato: 7.0 }, capacity_kg: { cauliflower: 1500, onion: 2400, potato: 3000, tomato: 4100 } }, // Dhamnod(F&V) (Dhar), 94 km from farmer centre
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
