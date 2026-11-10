import type { PublishedCards } from "./printCards";
import type {
  ConnState, Farmer, FarmerIn, Market, MarketIn, PlanMode, PlanResponse, SplitRule, Vehicle, VehicleIn,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, public readonly kind: "network" | "http", public readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClient {
  base: string;
  farmers(): Promise<Farmer[]>;
  vehicles(): Promise<Vehicle[]>;
  markets(): Promise<Market[]>;
  addFarmer(f: FarmerIn): Promise<Farmer>;
  addVehicles(v: VehicleIn): Promise<Vehicle[]>;
  addMarket(m: MarketIn): Promise<Market>;
  computePlan(mode?: PlanMode, splitRule?: SplitRule): Promise<PlanResponse>;
  fairness(planId: number): Promise<Fairness>;
  fleetUsage(planId: number): Promise<FleetUsage>;
  reset(): Promise<unknown>;
  issuePins(onlyMissing: boolean): Promise<{ issued: number; pins: { farmer_id: number; pin: string }[] }>;
  pinStatus(): Promise<PinStatus>;
  issuePin(farmerId: number): Promise<{ farmer_id: number; pin: string }>;
  publish(planId: number): Promise<PublishResult>;
  published(): Promise<{ published: boolean; plan_id?: number; published_at?: string; farmers?: number }>;
  unpublish(): Promise<unknown>;
  publishedCards(): Promise<PublishedCards>;
  phones(): Promise<PhoneSummary>;
  resetPhones(): Promise<{ cleared: number }>;
  clearPhone(farmerId: number): Promise<{ cleared: number }>;
  changeRequests(status: ChangeStatus): Promise<ChangeList>;
  previewChanges(ids: number[]): Promise<ChangePreview>;
  approveChanges(ids: number[], basePlanId: number): Promise<ChangeApproval>;
  rejectChange(id: number, reason: ChangeReason): Promise<unknown>;
  changeWindow(patch: { is_open?: boolean; plan_day?: string | null }): Promise<WindowState>;
}

/** Farmer change requests (see backend/change_requests.py). A farmer asks for a new quantity or time; the admin decides. */
export type ChangeStatus = "draft" | "pending" | "approved" | "rejected" | "superseded" | "expired" | "withdrawn";
export type ChangeReason = "too_late" | "not_possible" | "capacity" | "other";
/** from_day / to_day: whole days after the plan day for a time ("06:00" with to_day 1 is 06:00 the next day). Participation lines use from/to "in" | "out". */
export interface ChangeLine { field: "qty_kg" | "ready_hr" | "deadline_hr" | "active" | "trader_quote_per_kg"; label: string; from: string; to: string; from_day: number; to_day: number }
export interface ChangeRequest {
  id: number; farmer_id: number; crop: string | null; status: ChangeStatus;
  raw_text: string;                       // what the farmer typed, or "[form]"; untrusted: show as plain text
  changes: ChangeLine[]; reason_code: ChangeReason | null; applied_plan_id: number | null;
  created_at: number; decided_at: number | null;
  overlaps: number[];                     // other waiting requests of the same farmer that clash with this one
}
export interface ChangeList { requests: ChangeRequest[]; window_open: boolean; published_plan_id: number | null; plan_day: string; today: string }
/** is_open: may farmers send requests. plan_day: the admin's choice or null. effective_plan_day: the calendar date hour 0 of the plan means (the publish date when plan_day is null). */
export interface WindowState { is_open: boolean; plan_day: string | null; effective_plan_day: string; today: string }
export interface PlanDiff {
  farmers_changed: number; farmers_unchanged: number; farmers_only_in_old: number[]; farmers_only_in_new: number[];
  changed: { farmer_id: number; why: string[]; payout_change_inr: number }[];
}
export interface ChangePreview {
  base_plan_id: number; preview_plan_id: number; requested_farmer_ids: number[]; diff: PlanDiff; collateral_count: number;
}
export interface ChangeApproval { approved: number[]; plan_id: number; published: PublishResult; farmers_changed: number }

/** Farmer phone numbers for SMS / WhatsApp updates. Numbers arrive masked; full numbers never reach the console. */
export interface Fairness {
  farmers: number; by_status: { hauled: number; farmgate: number; unserved: number };
  gaining: number; share_gaining: number; total_gain_inr: number; gain_per_hauled_farmer_inr: number;
  gain_per_kg_p10_median_p90: (number | null)[]; min_hauled_gain_inr: number; max_hauled_gain_inr: number;
  gini_of_gains: number; bottom_fifth_share_of_gain: number; split_rules: string[]; notes: string[];
}

export interface FleetUsage {
  fleet_size: number; dispatched: number; idle: number; dispatched_pct: number; trips: number; spot_trips: number;
  avg_load_pct: number; unserved_kg: number; notes: string[];
  by_type: { class: string; owned: number; dispatched: number; idle: number; trips: number; avg_load_pct: number | null }[];
  unserved: { pool: number; farmers: number; kg: number; reason: string }[];
}

export interface PinStatus {
  farmers: number; with_pin: number;
  rows: { farmer_id: number; has_pin: boolean; issued_at: number | null; locked: boolean; failed_attempts: number }[];
}

export interface PhoneSummary {
  farmers: number;
  registered: number;
  providers: Record<"sms" | "whatsapp", { provider: string; live: boolean; problem: string | null }>;
  rows: { farmer_id: number; masked: string; lang: string; verified_at: number }[];
  recent: { farmer_id: number; channel: string; kind: string; ok: boolean; detail: string; plan_id: number | null; created_at: number; provider?: string; masked?: string | null }[];
}

export interface PublishResult {
  plan_id: number; published_at: string; farmers: number; farmers_without_pin: number[]; farmers_with_changes: number;
  phone_updates?: { farmers_messaged: number; sms: string; whatsapp: string; dry_run: boolean };
}

/** Typed client for the FastAPI backend. `onConn` reports reachability to the UI's connection chip. */
export function createApi(base: string, onConn: (s: ConnState) => void): ApiClient {
  async function req<T>(path: string, init?: RequestInit): Promise<T> {
    if (!base) throw new ApiError("Set the backend API base URL first.", "network");
    let res: Response;
    try {
      const send = () => {
        const h = new Headers(init?.headers);
        const t = localStorage.getItem("farmroute.adminToken");
        if (t) h.set("Authorization", `Bearer ${t}`);
        return fetch(base + path, { ...init, headers: h });
      };
      res = await send();
      if (res.status === 401) { // the backend has ADMIN_TOKEN set: ask once, remember it on this browser, retry
        const t = window.prompt("This backend needs the admin token.");
        if (t) { localStorage.setItem("farmroute.adminToken", t.trim()); res = await send(); }
      }
      onConn("ok");
    } catch {
      onConn("bad");
      throw new ApiError(`Could not reach ${base}. Is the backend running?`, "network");
    }
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch { /* not JSON */ }
      throw new ApiError(`${path} failed (${res.status})${detail ? ": " + detail : ""}`, "http", res.status);
    }
    return res.json() as Promise<T>;
  }
  const post = <T>(path: string, body?: unknown) =>
    req<T>(path, {
      method: "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

  return {
    base,
    farmers: () => req<Farmer[]>("/farmers"),
    vehicles: () => req<Vehicle[]>("/vehicles"),
    markets: () => req<Market[]>("/markets"),
    addFarmer: (f) => post<Farmer>("/farmers", f),
    addVehicles: (v) => post<Vehicle[]>("/vehicles", v),
    addMarket: (m) => post<Market>("/markets", m),
    computePlan: (mode = "returns", splitRule = "kg") => {
      const q = new URLSearchParams();
      if (mode !== "returns") q.set("mode", mode);
      if (splitRule !== "kg") q.set("split_rule", splitRule);
      return post<PlanResponse>("/plan/compute" + (q.toString() ? `?${q}` : ""));
    },
    fairness: (planId) => req<Fairness>(`/plan/${planId}/fairness`),
    fleetUsage: (planId) => req<FleetUsage>(`/plan/${planId}/fleet-usage`),
    reset: () => post("/reset"),
    issuePins: (onlyMissing) => post(`/farmers/pins?only_missing=${onlyMissing}`),
    pinStatus: () => req<PinStatus>("/farmers/pins"),
    issuePin: (farmerId) => post(`/farmers/${farmerId}/pin`),
    publish: (planId) => post(`/plan/${planId}/publish`),
    published: () => req("/published"),
    unpublish: () => req("/published", { method: "DELETE" }),
    publishedCards: () => req<PublishedCards>("/published/cards"),
    phones: () => req<PhoneSummary>("/farmers/phones"),
    resetPhones: () => req<{ cleared: number }>("/farmers/phones?confirm=true", { method: "DELETE" }),
    clearPhone: (id) => req<{ cleared: number }>(`/farmers/${id}/phone`, { method: "DELETE" }),
    changeRequests: (status) => req<ChangeList>(`/change-requests?status=${status}`),
    previewChanges: (ids) => post<ChangePreview>("/change-requests/preview", { ids }),
    approveChanges: (ids, basePlanId) => post<ChangeApproval>("/change-requests/approve", { ids, base_plan_id: basePlanId }),
    rejectChange: (id, reason) => post(`/change-requests/${id}/reject`, { reason_code: reason }),
    changeWindow: (patch) => req<WindowState>("/change-window", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
    }),
  };
}
