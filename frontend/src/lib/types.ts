// Types for the FastAPI backend (backend/schemas.py + the /plan/compute response).
// Plan summaries carry many optional numbers depending on which algorithm produced them.

export type Crop = "tomato" | "onion" | "potato" | "cauliflower" | "mango" | "spinach";

export interface FarmerIn {
  lat: number;
  lng: number;
  crop: string;
  qty_kg: number;
  ready_hr: number;
  deadline_hr: number;
  needs_refrigeration?: boolean | null;
}
export interface Farmer extends FarmerIn {
  id: number;
  needs_refrigeration: boolean;
  /** false once the farmer's request to leave the plan was approved: their row stays, but they are not planned */
  active?: boolean;
}

export interface VehicleIn { type_name: string; count: number }
export interface Vehicle {
  id: number;
  type_name: string;
  capacity_kg: number;
  refrigerated: boolean;
  fixed_cost: number;
  per_km_cost: number;
}
export interface VehicleType {
  name: string;
  capacity_kg: number;
  refrigerated: boolean;
  fixed_cost: number;
  per_km_cost: number;
}

export interface MarketIn {
  lat: number;
  lng: number;
  price: Record<string, number>;
  capacity_kg: Record<string, number>;
}
export interface Market extends MarketIn { id: number }

export interface ScenarioCategory { id: string; label: string }
/** Short labelled lists shown in a preset's expandable panel (e.g. Real / Synthetic / Assumptions). */
export interface ScenarioAbout { sections: { title: string; items: string[] }[] }
export interface Scenario {
  label: string;
  category: string;
  /** Legacy one-paragraph description; used only when `about` is absent. */
  blurb?: string;
  about?: ScenarioAbout;
  farmers: FarmerIn[];
  vehicles: VehicleIn[];
  markets: MarketIn[];
}

export type AlgoKey = "integrated_logistics_optimization" | "proximity_pooling" | "individual_transport";

export interface PlanSummary {
  total_qty_kg?: number;
  total_unsold_kg?: number;
  total_unserved_no_vehicle_kg?: number;
  total_withheld_kg?: number;
  total_spoilage_kg?: number;
  total_revenue?: number;
  total_transport_cost?: number;
  net_return?: number;
  net_return_per_farmer?: number;
  net_return_incl_farmgate?: number;
  net_return_per_farmer_incl_farmgate?: number;
  farmgate_revenue?: number;
  farmgate_kg?: number;
  farmgate_discount?: number;
  pct_qty_served?: number;
  pools_formed?: number;
  vehicles_used?: number;
  vehicle_utilization_pct?: number;
  [key: string]: number | undefined;
}

export interface Pool {
  farmer_ids?: number[];
  vehicle_id?: number | null;
  markets_used?: number[];
  total_qty_kg?: number;
  revenue?: number;
  transport_cost?: number;
  net_return?: number;
  spoilage_loss_kg?: number;
  unsold_kg?: number;
  unserved_no_vehicle_kg?: number;
  infeasible?: boolean;
  sold_at_farmgate?: boolean;
  withheld?: boolean;
  spot_hire?: boolean;
  no_truck_reason?: string;
}

export interface AlgoResult {
  summary?: PlanSummary;
  pools?: Pool[];
  farmgate_discount?: number;
}

/** What the optimizer aims for: farmer value (net return) or the least produce spoiled in transit. */
export type PlanMode = "returns" | "spoilage";
/** How a trip's surplus is shared: by kg only, or by what each farmer's lot is worth minus the cost they add. */
export type SplitRule = "kg" | "cost_aware";

export interface SpoilageFirstMeta {
  max_value_sacrifice: number;
  chosen_weight: number;
  returns_plan_value: number;
  returns_plan_spoilage_kg: number;
  frontier: { weight: number; value: number; spoilage_kg: number; unsold_kg: number; hauled_kg: number }[];
}

export interface RealisticMeta {
  chosen?: string;
  mode?: PlanMode;
  spoilage_first?: SpoilageFirstMeta;
}
export interface BehaviourAssumptions {
  max_haul_km: number;
  price_margin: number;
  spot_markup: number;
  spot_lead_hr: number;
}

export interface PlanResponse {
  id: number;
  integrated_logistics_optimization: AlgoResult;
  proximity_pooling: AlgoResult;
  individual_transport: AlgoResult;
  realistic_baselines?: {
    ilo_meta?: RealisticMeta;
    assumptions?: { behaviour?: BehaviourAssumptions };
  };
  [key: string]: unknown;
}

export interface SensorReading {
  timestamp: number;
  temperature: number;
  humidity: number;
}

export type ConnState = "unknown" | "ok" | "bad";
export type ViewName = "start" | "entry" | "dash" | "access" | "requests" | "compare" | "map";
