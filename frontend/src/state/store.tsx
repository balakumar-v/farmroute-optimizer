import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from "react";
import { ApiError, createApi, type ApiClient } from "../lib/api";
import { DEFAULT_API_BASE } from "../lib/constants";
import { SCENARIOS } from "../lib/scenarios";
import type {
  ConnState, Farmer, FarmerIn, Market, MarketIn, PlanMode, PlanResponse, Vehicle, VehicleIn,
} from "../lib/types";

export interface Toast { id: number; kind: "ok" | "err" | "info"; text: string }
export interface RunProgress { key: string; label: string; done: number; total: number }

export interface AppState {
  apiBase: string;
  conn: ConnState;
  farmers: Farmer[];
  vehicles: Vehicle[];
  markets: Market[];
  tables: "idle" | "loading" | "ready" | "error";
  tablesError: string;
  plan: PlanResponse | null;
  /** true when data changed after the current plan was computed */
  planStale: boolean;
  planStatus: "idle" | "computing" | "error";
  planError: string;
  /** what the next computed plan optimises for (the plan on screen reports its own mode in ilo_meta) */
  planMode: PlanMode;
  run: RunProgress | null;
  runError: string;
  runNote: string;
  toasts: Toast[];
}

const API_BASE_KEY = "fpoApiBase";

function initialApiBase(): string {
  try {
    const saved = localStorage.getItem(API_BASE_KEY);
    if (saved) return saved;
  } catch { /* storage unavailable */ }
  return DEFAULT_API_BASE;
}

const initial: AppState = {
  apiBase: initialApiBase(),
  conn: "unknown",
  farmers: [], vehicles: [], markets: [],
  tables: "idle", tablesError: "",
  plan: null, planStale: false, planStatus: "idle", planError: "", planMode: "returns",
  run: null, runError: "", runNote: "",
  toasts: [],
};

type Action = { type: "patch"; patch: Partial<AppState> } | { type: "toast"; toast: Toast } | { type: "untoast"; id: number };

function reducer(s: AppState, a: Action): AppState {
  switch (a.type) {
    case "patch": return { ...s, ...a.patch };
    case "toast": return { ...s, toasts: [...s.toasts.slice(-3), a.toast] };
    case "untoast": return { ...s, toasts: s.toasts.filter((t) => t.id !== a.id) };
  }
}

export interface Actions {
  api: ApiClient;
  setApiBase(url: string): Promise<boolean>;
  loadTables(): Promise<void>;
  addFarmer(f: FarmerIn): Promise<void>;
  addVehicles(v: VehicleIn): Promise<void>;
  addMarket(m: MarketIn): Promise<void>;
  computePlan(): Promise<PlanResponse | null>;
  setPlanMode(mode: PlanMode): void;
  runScenario(key: string): Promise<boolean>;
  resetAll(): Promise<void>;
  toast(kind: Toast["kind"], text: string): void;
  dismissToast(id: number): void;
}

const Ctx = createContext<{ state: AppState; actions: Actions } | null>(null);

export function useApp() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);
  const stateRef = useRef(state);
  stateRef.current = state;
  const patch = useCallback((p: Partial<AppState>) => dispatch({ type: "patch", patch: p }), []);
  const toastId = useRef(0);

  const api = useMemo(() => createApi(state.apiBase, (conn) => {
    if (stateRef.current.conn !== conn) dispatch({ type: "patch", patch: { conn } });
  }), [state.apiBase]);
  const apiRef = useRef(api);
  apiRef.current = api;

  const toast = useCallback((kind: Toast["kind"], text: string) => {
    const id = ++toastId.current;
    dispatch({ type: "toast", toast: { id, kind, text } });
    window.setTimeout(() => dispatch({ type: "untoast", id }), kind === "err" ? 7000 : 3500);
  }, []);

  const loadTables = useCallback(async () => {
    patch({ tables: "loading", tablesError: "" });
    try {
      const [farmers, vehicles, markets] = await Promise.all([apiRef.current.farmers(), apiRef.current.vehicles(), apiRef.current.markets()]);
      patch({ farmers, vehicles, markets, tables: "ready" });
    } catch (e) {
      patch({ tables: "error", tablesError: msg(e) });
    }
  }, [patch]);

  const markStale = useCallback(() => {
    if (stateRef.current.plan) patch({ planStale: true });
  }, [patch]);

  const actions = useMemo<Actions>(() => ({
    get api() { return apiRef.current; },

    async setApiBase(url) {
      const base = url.trim().replace(/\/$/, "");
      try { localStorage.setItem(API_BASE_KEY, base); } catch { /* ignore */ }
      patch({ apiBase: base, conn: "unknown" });
      // wait a tick so apiRef points at the new client
      await new Promise((r) => setTimeout(r, 0));
      await loadTables();
      return stateRef.current.conn === "ok";
    },

    loadTables,

    async addFarmer(f) { await apiRef.current.addFarmer(f); await loadTables(); markStale(); },
    async addVehicles(v) { await apiRef.current.addVehicles(v); await loadTables(); markStale(); },
    async addMarket(m) { await apiRef.current.addMarket(m); await loadTables(); markStale(); },

    setPlanMode(mode) { patch({ planMode: mode }); },

    async computePlan() {
      patch({ planStatus: "computing", planError: "" });
      try {
        const plan = await apiRef.current.computePlan(stateRef.current.planMode);
        patch({ plan, planStale: false, planStatus: "idle" });
        return plan;
      } catch (e) {
        patch({ planStatus: "error", planError: msg(e) });
        return null;
      }
    },

    async runScenario(key) {
      const sc = SCENARIOS[key];
      if (!sc || stateRef.current.run) return false;
      const a = apiRef.current;
      const total = 1 + sc.farmers.length + sc.vehicles.length + sc.markets.length + 1;
      let done = 0;
      const step = (label: string) => patch({ run: { key, label, done, total }, runError: "", runNote: label });
      try {
        step("Clearing previous data");
        await a.reset();
        patch({ plan: null, planStale: false, planError: "" });
        done++;
        for (let i = 0; i < sc.farmers.length; i++) {
          step(`Loading farmers (${i + 1} of ${sc.farmers.length})`);
          await a.addFarmer(sc.farmers[i]);
          done++;
        }
        for (const v of sc.vehicles) { step("Loading vehicles"); await a.addVehicles(v); done++; }
        for (const m of sc.markets) { step("Loading markets"); await a.addMarket(m); done++; }
        step("Computing the plan (large scenarios take a few seconds)");
        await loadTables();
        const plan = await a.computePlan(stateRef.current.planMode);
        patch({ plan, planStale: false, planStatus: "idle", run: null, runNote: "" });
        return true;
      } catch (e) {
        patch({ run: null, runError: msg(e), runNote: "" });
        return false;
      }
    },

    async resetAll() {
      try {
        await apiRef.current.reset();
        patch({ plan: null, planStale: false, planError: "" });
        await loadTables();
        toast("ok", "Cleared all farmers, vehicles, markets and plans on the backend.");
      } catch (e) {
        toast("err", msg(e));
      }
    },

    toast,
    dismissToast(id) { dispatch({ type: "untoast", id }); },
  }), [patch, loadTables, markStale, toast]);

  // initial load + re-check when the base URL changes
  useEffect(() => { void loadTables(); }, [loadTables, state.apiBase]);

  const value = useMemo(() => ({ state, actions }), [state, actions]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export { ApiError };
