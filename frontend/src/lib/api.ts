import type { PublishedCards } from "./printCards";
import type {
  ConnState, Farmer, FarmerIn, Market, MarketIn, PlanMode, PlanResponse, Vehicle, VehicleIn,
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
  computePlan(mode?: PlanMode): Promise<PlanResponse>;
  reset(): Promise<unknown>;
  issuePins(onlyMissing: boolean): Promise<{ issued: number; pins: { farmer_id: number; pin: string }[] }>;
  publish(planId: number): Promise<PublishResult>;
  published(): Promise<{ published: boolean; plan_id?: number; published_at?: string; farmers?: number }>;
  unpublish(): Promise<unknown>;
  publishedCards(): Promise<PublishedCards>;
}

export interface PublishResult {
  plan_id: number; published_at: string; farmers: number; farmers_without_pin: number[]; farmers_with_changes: number;
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
    computePlan: (mode = "returns") => post<PlanResponse>(mode === "returns" ? "/plan/compute" : "/plan/compute?mode=spoilage"),
    reset: () => post("/reset"),
    issuePins: (onlyMissing) => post(`/farmers/pins?only_missing=${onlyMissing}`),
    publish: (planId) => post(`/plan/${planId}/publish`),
    published: () => req("/published"),
    unpublish: () => req("/published", { method: "DELETE" }),
    publishedCards: () => req<PublishedCards>("/published/cards"),
  };
}
