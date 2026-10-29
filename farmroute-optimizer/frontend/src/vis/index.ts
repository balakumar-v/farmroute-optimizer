// Typed entry point for the imperative map/simulation engine (the MapLibre + deck.gl ES modules in this folder).
// The engine modules stay JavaScript; this file defines the surface the React app is allowed to use.
import { Vis as VisNamespace } from "./namespace.js";
import "./adapter.js";
import "./icons.js";
import "./models3d.js";
import "./simulationEngine.js";
import "./narrator.js";
import "./panels.js";
import "./logisticsMap.js";
import "./theater.js";
import type { SensorReading } from "../lib/types";

export interface VizVehicle { id: number | string; used?: boolean; [k: string]: unknown }
export interface VizSolution {
  vehicles: VizVehicle[];
  farmgateFarmerIds?: Array<number | string>;
  simulationEvents: unknown[];
  routes: unknown[];
  [k: string]: unknown;
}
export interface RoadsInfo { enabled: boolean; provider: string | null; profile: string | null; pending: Record<string, number> }
export interface RoadsProgress { algo: string; enabled: boolean; provider: string | null; total: number; pending: number; resolved: number; failed: number; error: string | null }
export interface DistanceModel { type: "road_matrix" | "circuity" | "straight"; k?: number; ratio?: number; source?: string; note?: string; provider?: string }
export interface VizPayload { id: number; solutions: Record<string, VizSolution>; roads?: RoadsInfo; distanceModel?: DistanceModel; [k: string]: unknown }

export interface EngineSnapshot {
  t: number;
  playing: boolean;
  vehiclePositions: unknown;
  visitedFarmerIds: unknown;
  visitedMarketIds: unknown;
  visitedGeneration: number;
}
export interface SimEngine {
  t: number; minT: number; maxT: number; playing: boolean; speed: number; readonly progress: number;
  on(fn: (snap: EngineSnapshot) => void): () => void;
  play(): void; pause(): void; reset(): void;
  setSpeed(hoursPerSecond: number): void;
  seek(t: number): void; seekProgress(p: number): void;
  snapshot(): EngineSnapshot;
  positionOfTrip(tripId: string, t?: number): unknown;
}

export interface Selection { type: string; id: number | string; object: unknown }
export interface MapController {
  map: { resize(): void } | null;
  mode3d: boolean;
  follow: unknown;
  onSelect: ((type: string, id: number | string, object: unknown) => void) | null;
  onMapError: ((msg: string) => void) | null;
  init(): Promise<void>;
  destroy(): void;
  resize(): void;
  setSolution(s: VizSolution): void;
  setCompareSolution(s: VizSolution | null): void;
  setStage(stage: number): void;
  setVehiclePositions(p: unknown): void;
  setVisitedSets(farmers: unknown, markets: unknown, generation: number): void;
  set3D(on: boolean): void;
  setFollow(opts: { mode: "chase" | "top"; vehicleId?: number | string; zoom?: number } | null): void;
}
export interface StoryStep { t: number; [k: string]: unknown }
export interface Story { applyTime(t: number): void }
export interface Theater { isOpen: boolean; open(realMapContainerEl: HTMLElement): void; close(): void }

export interface TheaterOptions {
  overlayEl: HTMLElement; mapSlotEl: HTMLElement; map: MapController; legendEl: HTMLElement | null;
  getSolution: () => VizSolution | undefined;
  getEngine: () => SimEngine | null;
  onClose: () => void;
  on3DChange: () => void;
  els: Record<"caption" | "prevBtn" | "nextBtn" | "exitBtn" | "freeLookBtn" | "view3dBtn" | "chaseBtn" | "followLabel" | "progressText" | "progressFill", HTMLElement>;
}

export interface VisApi {
  config?: { tileUrl: string | null; tileAttribution: string | null; tileMaxZoom: number | null };
  STAGE_BLURBS: Record<number, string>;
  STATUS_COLORS: Record<"unserved" | "farmgate" | "unvisited" | "visited", number[]>;
  MARKET_COLOR: number[];
  colorForIdCss(id: number | string): string;
  fetchVisualization(apiBase: string, planId: number): Promise<VizPayload>;
  fetchSensorReadings(apiBase: string, poolId: string): Promise<SensorReading[]>;
  resolveRoads(apiBase: string, planId: number, algo: string, budgetS?: number): Promise<RoadsProgress>;
  buildNarrative(solution: VizSolution): StoryStep[];
  StoryTimeline: new (container: HTMLElement, steps: StoryStep[], opts: { onStepClick: (s: StoryStep) => void }) => Story;
  renderDetailsPanel(container: HTMLElement, selection: Selection | null, solution: VizSolution | null | undefined, snapshot: EngineSnapshot | null): void;
  renderComparisonPanel(container: HTMLElement, solutions: Record<string, VizSolution>): void;
  LogisticsMap: new (container: HTMLElement) => MapController;
  SimulationEngine: new (events: unknown[], routes: unknown[]) => SimEngine;
  TheaterMode: new (opts: TheaterOptions) => Theater;
}

export const Vis = VisNamespace as unknown as VisApi;
