import type {
  ConnState, Farmer, FarmerIn, Market, MarketIn, PlanResponse, Vehicle, VehicleIn,
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
  computePlan(): Promise<PlanResponse>;
  reset(): Promise<unknown>;
}

/** Typed client for the FastAPI backend. `onConn` reports reachability to the UI's connection chip. */
export function createApi(base: string, onConn: (s: ConnState) => void): ApiClient {
  async function req<T>(path: string, init?: RequestInit): Promise<T> {
    if (!base) throw new ApiError("Set the backend API base URL first.", "network");
    let res: Response;
    try {
      res = await fetch(base + path, init);
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
    computePlan: () => post<PlanResponse>("/plan/compute"),
    reset: () => post("/reset"),
  };
}
