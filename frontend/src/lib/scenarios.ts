// Demo scenarios (ported verbatim from the legacy app.js; data unchanged).
import type { ScenarioCategory, Scenario } from "./types";

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
export const SCENARIO_CATEGORIES: ScenarioCategory[] = [
  { id: "synthetic", label: "Synthetic scenarios" },
  { id: "real", label: "Real data" },
];
export const SCENARIOS: Record<string, Scenario> = {
  cold_chain: {
    label: "1. Cold chain: refrigeration-aware pooling",
    category: "synthetic",
    about: {"sections": [{"title": "Setup", "items": ["11 farmers, all growing crops that need refrigeration", "Fleet: ONE refrigerated vehicle plus 3 ordinary trucks", "Mandis about 6 km away"]}, {"title": "Watch", "items": ["Spoilage (kg) and farmer value", "Both baselines hire ordinary trucks and never check whether a load needs refrigeration, so perishables ride unrefrigerated"]}, {"title": "Expect", "items": ["Spoilage is small at these distances and the baselines finish about level with ILO: this shows the mechanism, not a win"]}]},
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
    about: {"sections": [{"title": "Setup", "items": ["10 onion farmers", "Three markets: one small high-price, one mid-price/mid-capacity, one large low-price wholesale", "Total supply is over 4x the best market's capacity"]}, {"title": "Watch", "items": ["Coverage (%) and net return", "The baselines cannot reroute overflow to the next-best market once their first choice fills up, so most of the crop goes unsold"]}]},
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
    about: {"sections": [{"title": "Setup", "items": ["15 potato farmers in one neighborhood, sharing only 3 vehicles", "Morning group: ready hour 0, strict deadline by hour ~3-4", "Afternoon group: ready hour ~6-7.5, deadline by hour ~12-13.5", "The baselines hire their own trucks, so only ILO is held to the 3-vehicle fleet"]}, {"title": "Watch", "items": ["Coverage (%) and farmer value", "ILO leaves some produce unhauled rather than run losing trips", "Proximity Pooling groups purely by location and waits for the last member, so the strict-deadline morning farmers miss pickup and sell at the farm gate"]}]},
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
    about: {"sections": [{"title": "Real", "items": ["8 Bihar mandis: Aarah, Piro, Tajpur, Natwar, Buxar, Chakia, Sheohar, Sasaram", "Potato and onion prices: Agmarknet via India Data Portal, 1 Dec 2025 to 28 Feb 2026 (median daily modal price; one window for every mandi, so one season)", "Coordinates: OpenStreetMap; Piro and Natwar from public place listings (Natwar uncertain by ~9 km)"]}, {"title": "Synthetic", "items": ["34 farmers (same generator and seed as the previous preset, so only the mandis changed)", "8-vehicle fleet", "No public farmer or fleet data exists"]}, {"title": "Assumptions", "items": ["Mandi capacity = median reported daily arrival: a proxy, not a hard limit", "The farm-gate price used in the comparison is assumed"]}, {"title": "Data caveats", "items": ["Aarah, Tajpur, Natwar, Buxar and Chakia repeat one capacity value on 95%+ of days: treat it as an assumption", "Piro (the farmers' own district) stopped reporting on 23 Feb, so its prices rest on 18 days", "Left out: Barahat (184 km+ from every farmer); Brahmpur, Motihari, Bahadurganj (no reliable coordinates)"]}]},
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
    about: {"sections": [{"title": "Real", "items": ["8 Karnataka mandis: Binny Mill (F&V), Bengaluru, Bengaluru, Doddaballapur, Ramanagara, Kanakapura, Channapatna, Chickkaballapura, Kolar", "Prices and daily arrivals: Agmarknet via India Data Portal, 2026-02-01 to 2026-04-30 (median of days)", "Mandi coordinates: the portal's own"]}, {"title": "Synthetic", "items": ["61 farmers (onion 18, tomato 17, potato 16, mango 7, cauliflower 3) in villages within 18 km of (12.96, 77.54); lots 150-600 kg", "16-vehicle fleet, 39 t = 1.5x the day's 23.9 t of produce", "No public farmer or fleet data exists"]}, {"title": "Assumptions", "items": ["Mandi capacity = median reported daily arrival: a proxy, not a hard limit (0 of 21 series repeat one value on 70%+ of days)", "About 60 pickups per round, never more than 30% of a crop's daily absorption by these mandis", "The farm-gate price used in the comparison is assumed"]}, {"title": "Cleaning", "items": ["79 rows dropped (price or arrival outliers, invalid prices); 0 series with implausible units dropped", "0 mandis without coordinates and 0 with suspect ones left out", "9 mandi-crop series absorbing under 1 t/day removed (too small for a pickup round)"]}]},
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
    about: {"sections": [{"title": "Real", "items": ["8 Uttar Pradesh mandis: Aligarh, Atrauli, Khair, Charra, Haathras, Sikarpur, Khurja, Sikandraraau", "Prices and daily arrivals: Agmarknet via India Data Portal, 2025-11-01 to 2026-01-31 (median of days)", "Mandi coordinates: the portal's own"]}, {"title": "Synthetic", "items": ["59 farmers (potato 31, onion 9, tomato 7, cauliflower 7, spinach 5) in villages within 18 km of (27.95, 78.11); lots 150-600 kg", "15-vehicle fleet, 33 t = 1.5x the day's 23.5 t of produce", "No public farmer or fleet data exists"]}, {"title": "Assumptions", "items": ["Mandi capacity = median reported daily arrival: a proxy, not a hard limit (1 of 26 series repeat one value on 70%+ of days; it was raised to the state's lower quartile)", "About 60 pickups per round, never more than 30% of a crop's daily absorption by these mandis", "The farm-gate price used in the comparison is assumed"]}, {"title": "Cleaning", "items": ["51 rows dropped (price or arrival outliers, invalid prices); 1 series with implausible units dropped", "0 mandis without coordinates and 0 with suspect ones left out", "36 mandi-crop series absorbing under 1 t/day removed (too small for a pickup round)"]}]},
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
    about: {"sections": [{"title": "Real", "items": ["8 Maharashtra mandis: Junnar (Narayangaon), Manchar, Junnar (Alephata), Junnar (Otur), Khed, Khed (Chakan), Pune (Moshi), Parner", "Prices and daily arrivals: Agmarknet via India Data Portal, 2026-02-01 to 2026-04-30 (median of days)", "Mandi coordinates: the portal's own"]}, {"title": "Synthetic", "items": ["60 farmers (onion 34, tomato 10, cauliflower 8, potato 8) in villages within 18 km of (19.05, 73.98); lots 150-600 kg", "14-vehicle fleet, 32 t = 1.5x the day's 21.9 t of produce", "No public farmer or fleet data exists"]}, {"title": "Assumptions", "items": ["Mandi capacity = median reported daily arrival: a proxy, not a hard limit (0 of 22 series repeat one value on 70%+ of days)", "About 60 pickups per round, never more than 30% of a crop's daily absorption by these mandis", "The farm-gate price used in the comparison is assumed"]}, {"title": "Cleaning", "items": ["34 rows dropped (price or arrival outliers, invalid prices); 13 series with implausible units dropped", "5 mandis without coordinates and 0 with suspect ones left out", "12 mandi-crop series absorbing under 1 t/day removed (too small for a pickup round)"]}]},
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
    about: {"sections": [{"title": "Real", "items": ["11 Madhya Pradesh mandis: Dewas (F&V), Ujjain, Indore, Badnawar, Shajapur (F&V), Shajapur, Kalapipal, Ashta, Sarangpur, Ratlam, Dhamnod (F&V)", "Prices and daily arrivals: Agmarknet via India Data Portal, 2026-02-01 to 2026-04-30 (median of days)", "Mandi coordinates: the portal's own"]}, {"title": "Synthetic", "items": ["57 farmers (onion 30, potato 27) in villages within 18 km of (22.97, 75.87); lots 150-600 kg", "13-vehicle fleet, 30 t = 1.5x the day's 20.6 t of produce", "No public farmer or fleet data exists"]}, {"title": "Assumptions", "items": ["Mandi capacity = median reported daily arrival: a proxy, not a hard limit (0 of 21 series repeat one value on 70%+ of days)", "About 60 pickups per round, never more than 30% of a crop's daily absorption by these mandis", "The farm-gate price used in the comparison is assumed"]}, {"title": "Cleaning", "items": ["47 rows dropped (price or arrival outliers, invalid prices); 0 series with implausible units dropped", "27 mandis without coordinates and 0 with suspect ones left out", "23 mandi-crop series absorbing under 1 t/day removed (too small for a pickup round)"]}]},
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
  tamil_nadu_vellore: {
    category: "real",
    label: "Tamil Nadu mandis around Vellore, Jan-Feb 2026: tomato & onion",
    about: {"sections": [{"title": "Real", "items": ["7 Tamil Nadu mandis: Katpadi, Vellore, Vaniyampadi, Natrampalli, Tindivanam, Kallakurichi, Ulundurpettai", "Prices and daily arrivals: Agmarknet via India Data Portal, 2026-01-04 to 2026-02-08 (median of days)", "Mandi coordinates: the portal's own"]}, {"title": "Synthetic", "items": ["20 farmers (tomato 16, onion 4) in villages within 18 km of (12.98, 79.20); lots 150-600 kg", "5-vehicle fleet, 12 t = 1.5x the day's 7.9 t of produce", "No public farmer or fleet data exists"]}, {"title": "Assumptions", "items": ["Mandi capacity = median reported daily arrival: a proxy, not a hard limit", "About 60 pickups per round, never more than 30% of a crop's daily absorption by these mandis", "The farm-gate price used in the comparison is assumed"]}, {"title": "Data caveats", "items": ["Only 5 days sampled per mandi, all Sundays (4, 18 and 25 Jan, 1 and 8 Feb): each price is a median of at most 5 days", "Most yards are Uzhavar Sandhai (farmers' markets), so prices look retail-like; only Vellore, Tindivanam and Ulundurpettai are APMC wholesale yards", "Only 28 of 179 Tamil Nadu mandis have coordinates (none in Chennai), so the region is capped at 150 km around Vellore", "Thresholds lowered for this preset: 5 days per series (default 15) and 0.3 t/day (default 1 t)"]}, {"title": "Cleaning", "items": ["0 rows dropped (price or arrival outliers, invalid prices); 0 series with implausible units (e.g. bundle prices) dropped", "131 mandis without coordinates and 0 with suspect ones left out", "35 mandi-crop series absorbing under 0.3 t/day removed (too small for a pickup round)"]}]},
    farmers: [
      { lat: 12.89346, lng: 79.23188, crop: "tomato", qty_kg: 502.3, ready_hr: 0.02, deadline_hr: 7.26 },
      { lat: 12.90194, lng: 79.20613, crop: "tomato", qty_kg: 489.2, ready_hr: 0.23, deadline_hr: 12.91 },
      { lat: 13.03117, lng: 79.02945, crop: "tomato", qty_kg: 581.6, ready_hr: 0.26, deadline_hr: 12.97 },
      { lat: 12.98276, lng: 79.30247, crop: "tomato", qty_kg: 194.2, ready_hr: 0.52, deadline_hr: 9.26 },
      { lat: 12.91851, lng: 79.21998, crop: "tomato", qty_kg: 566.5, ready_hr: 0.9, deadline_hr: 13.74 },
      { lat: 12.9321, lng: 79.22874, crop: "tomato", qty_kg: 350.5, ready_hr: 1.21, deadline_hr: 11.6 },
      { lat: 13.01493, lng: 79.04942, crop: "tomato", qty_kg: 259.7, ready_hr: 1.3, deadline_hr: 11.99 },
      { lat: 13.01036, lng: 79.28381, crop: "tomato", qty_kg: 324.8, ready_hr: 1.39, deadline_hr: 11.54 },
      { lat: 12.98031, lng: 79.11989, crop: "tomato", qty_kg: 156.9, ready_hr: 1.56, deadline_hr: 9.64 },
      { lat: 12.97562, lng: 79.28706, crop: "tomato", qty_kg: 291.8, ready_hr: 1.76, deadline_hr: 13.31 },
      { lat: 12.96266, lng: 79.09913, crop: "onion", qty_kg: 541.6, ready_hr: 1.91, deadline_hr: 14.16 },
      { lat: 12.90048, lng: 79.20774, crop: "tomato", qty_kg: 488.1, ready_hr: 2.2, deadline_hr: 11.15 },
      { lat: 13.04516, lng: 79.04884, crop: "tomato", qty_kg: 523.7, ready_hr: 2.35, deadline_hr: 13.83 },
      { lat: 12.99129, lng: 79.08245, crop: "tomato", qty_kg: 333.5, ready_hr: 2.65, deadline_hr: 10.83 },
      { lat: 12.9556, lng: 79.1037, crop: "onion", qty_kg: 529.8, ready_hr: 3.14, deadline_hr: 9.28 },
      { lat: 12.91211, lng: 79.22087, crop: "tomato", qty_kg: 406.3, ready_hr: 3.37, deadline_hr: 13.07 },
      { lat: 12.9207, lng: 79.23757, crop: "onion", qty_kg: 327.9, ready_hr: 3.57, deadline_hr: 10.16 },
      { lat: 13.03167, lng: 79.04931, crop: "tomato", qty_kg: 463.7, ready_hr: 3.66, deadline_hr: 15.94 },
      { lat: 13.01647, lng: 79.28829, crop: "tomato", qty_kg: 221.3, ready_hr: 3.78, deadline_hr: 13.78 },
      { lat: 12.96337, lng: 79.10685, crop: "onion", qty_kg: 309.2, ready_hr: 3.79, deadline_hr: 11.67 },
    ],
    vehicles: [
      { type_name: "truck_2t", count: 1 },
      { type_name: "reefer_5t", count: 1 },
      { type_name: "reefer_2t", count: 2 },
      { type_name: "reefer_van", count: 1 },
    ],
    markets: [
      { lat: 13.06805, lng: 79.26444, price: { onion: 32.0 }, capacity_kg: { onion: 1700 } }, // Katpadi (Uzhavar Sandhai ) (Vellore), 12 km from farmer centre
      { lat: 12.89844, lng: 79.13112, price: { onion: 27.0, potato: 27.5, tomato: 21.0 }, capacity_kg: { onion: 1300, potato: 650, tomato: 3800 } }, // Vellore (Vellore), 12 km from farmer centre
      { lat: 12.65515, lng: 78.60751, price: { onion: 30.0, potato: 30.0, tomato: 25.0 }, capacity_kg: { onion: 700, potato: 700, tomato: 9080 } }, // Vaniyampadi(Uzhavar Sandhai ) (Tirupathur), 74 km from farmer centre
      { lat: 12.48572, lng: 78.56687, price: { onion: 27.5, potato: 32.5, tomato: 22.5 }, capacity_kg: { onion: 550, potato: 300, tomato: 6180 } }, // Natrampalli(Uzhavar Sandhai ) (Tirupathur), 88 km from farmer centre
      { lat: 12.24492, lng: 79.64416, price: { onion: 27.5, tomato: 20.0 }, capacity_kg: { onion: 900, tomato: 900 } }, // Tindivanam (Viluppuram), 95 km from farmer centre
      { lat: 11.73884, lng: 78.95356, price: { onion: 35.0, tomato: 25.0 }, capacity_kg: { onion: 320, tomato: 830 } }, // Kallakurichi(Uzhavar Sandhai ) (Kallakurichi), 141 km from farmer centre
      { lat: 11.69216, lng: 79.28642, price: { onion: 40.0, tomato: 35.0 }, capacity_kg: { onion: 470, tomato: 420 } }, // Ulundurpettai (Viluppuram), 144 km from farmer centre
    ],
  },
};
