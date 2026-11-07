import type { AlgoKey, VehicleType } from "./types";

// Mirrors CROPS / VEHICLE_TYPES in backend/logistics_lib_v2.py. The API has no
// "list valid crops/vehicle types" endpoint, so keep these in sync by hand.
export const CROPS = ["tomato", "onion", "potato", "cauliflower", "mango", "spinach"] as const;

export const VEHICLE_TYPES: VehicleType[] = [
  { name: "mini_pickup", capacity_kg: 500, refrigerated: false, fixed_cost: 500, per_km_cost: 14 },
  { name: "van", capacity_kg: 1000, refrigerated: false, fixed_cost: 900, per_km_cost: 18 },
  { name: "reefer_van", capacity_kg: 1000, refrigerated: true, fixed_cost: 1300, per_km_cost: 21 },
  { name: "truck_2t", capacity_kg: 2000, refrigerated: false, fixed_cost: 1700, per_km_cost: 20 },
  { name: "reefer_2t", capacity_kg: 2000, refrigerated: true, fixed_cost: 2200, per_km_cost: 24 },
  { name: "truck_5t", capacity_kg: 5000, refrigerated: false, fixed_cost: 3200, per_km_cost: 27 },
  { name: "reefer_5t", capacity_kg: 5000, refrigerated: true, fixed_cost: 4000, per_km_cost: 32 },
];

export const ALGO_KEYS: AlgoKey[] = ["integrated_logistics_optimization", "proximity_pooling", "individual_transport"];

export const ALGO_NAME: Record<AlgoKey, string> = {
  integrated_logistics_optimization: "ILO (ours)",
  proximity_pooling: "Proximity Pooling",
  individual_transport: "Individual Transport",
};

export const ALGO_BLURB: Record<AlgoKey, string> = {
  integrated_logistics_optimization:
    "Hauls only what beats selling at the farm gate. Merges farmers heading to the same mandi into full trucks, respects refrigeration and pickup windows, picks the best set of trips with an exact solver, and splits produce across markets so overflow reroutes to the next-best one.",
  proximity_pooling:
    "Up to 4 neighbours within 5 km share one hired truck to the nearest mandi, if it is within reach and clearly beats the trader's offer. No profit check, no refrigeration or window planning, no rerouting.",
  individual_transport:
    "Each farmer hires a truck to the nearest mandi, if it is within reach and clearly beats the trader's offer; otherwise sells at the farm gate. No profit check, no pooling.",
};

export const VIEWS = [
  { id: "start", label: "Scenarios", icon: "list" },
  { id: "entry", label: "Data", icon: "table" },
  { id: "dash", label: "Plan", icon: "route" },
  { id: "requests", label: "Requests", icon: "chat" },
  { id: "compare", label: "Compare", icon: "bars" },
  { id: "map", label: "Map", icon: "map" },
] as const;

export const DEFAULT_API_BASE: string =
  (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE || "http://localhost:8000";
