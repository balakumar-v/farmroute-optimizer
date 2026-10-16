import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { StaleBanner } from "../components/Shell";
import { fmt } from "../lib/format";
import type { SensorReading, ViewName } from "../lib/types";
import { useApp } from "../state/store";
import {
  Vis, type EngineSnapshot, type MapController, type Selection, type SimEngine, type Story, type Theater,
  type VizPayload, type VizSolution,
} from "../vis";

const ILO = "integrated_logistics_optimization";
const ALGO_OPTIONS: Array<[string, string]> = [[ILO, "Our System (ILO)"], ["individual_transport", "Individual Transport"], ["proximity_pooling", "Proximity Pooling"]];
const STAGES = ["Farmers", "Pooling", "Vehicles", "Markets", "Routes", "Transport", "Delivery"];
const compareAlgoFor = (algo: string) => (algo === ILO ? "individual_transport" : ILO);

const store = {
  get(key: string): string | null { try { return localStorage.getItem(key); } catch { return null; } },
  set(key: string, v: string) { try { localStorage.setItem(key, v); } catch { /* ignore */ } },
};

interface Ui {
  ready: boolean;
  loading: boolean;
  error: string;
  note: string;
  payload: VizPayload | null;
  loadedPlanId: number | null;
  algo: string;
  compareOn: boolean;
  stage: number;
  selection: Selection | null;
  sidePane: "story" | "details";
  mode3d: boolean;
  chase: boolean;
  engineKey: number;
}
const initialUi: Ui = {
  ready: false, loading: false, error: "", note: "", payload: null, loadedPlanId: null, algo: ILO, compareOn: false,
  stage: 1, selection: null, sidePane: "story", mode3d: false, chase: false, engineKey: 0,
};

/** Timeline controls. Owns the per-frame snapshot so the rest of the map view does not re-render at 60 fps. */
function Transport({ engine, speed, setSpeed, reduced, setReduced, onPlayChange }: {
  engine: SimEngine | null; speed: number; setSpeed: (n: number) => void; reduced: boolean; setReduced: (b: boolean) => void; onPlayChange: () => void;
}) {
  const [snap, setSnap] = useState<{ t: number; playing: boolean; progress: number }>({ t: 0, playing: false, progress: 0 });
  const dragging = useRef(false);
  useEffect(() => {
    if (!engine) { setSnap({ t: 0, playing: false, progress: 0 }); return; }
    const read = (s: EngineSnapshot) => setSnap({ t: s.t, playing: s.playing, progress: engine.progress });
    read(engine.snapshot());
    return engine.on(read);
  }, [engine]);

  const toggle = () => {
    if (!engine || reduced) return;
    if (engine.playing) engine.pause(); else engine.play();
    setSnap((s) => ({ ...s, playing: engine.playing }));
    onPlayChange();
  };
  return (
    <div className="transport" aria-label="Simulation timeline">
      <button id="simPlayBtn" className="btn btn-primary" type="button" disabled={!engine || reduced} onClick={toggle} title="Space">
        <Icon name={snap.playing ? "pause" : "play"} /><span>{snap.playing ? "Pause" : "Play"}</span>
      </button>
      <button id="simResetBtn" className="btn btn-secondary btn-icon" type="button" aria-label="Reset simulation" title="Reset" disabled={!engine} onClick={() => engine?.reset()}><Icon name="reset" small={false} /></button>
      <input type="range" id="simScrubber" min={0} max={1000} step={1} aria-label="Simulation time" disabled={!engine}
        value={dragging.current ? undefined : Math.round(snap.progress * 1000)}
        onChange={(e) => { if (!engine) return; engine.pause(); engine.seekProgress(Number(e.target.value) / 1000); }} />
      <span id="simTimeReadout" className="readout">t = {fmt(snap.t, 2)} hr</span>
      <label className="speed"><span className="sr-only">Playback speed</span>
        <select id="simSpeedSelect" title="Playback speed" value={speed} disabled={reduced} onChange={(e) => setSpeed(Number(e.target.value))}>
          {[1, 2, 4, 10].map((n) => <option key={n} value={n}>{n}&times;</option>)}
        </select>
      </label>
      <label className="reduced-motion-toggle"><input type="checkbox" id="simReducedMotion" checked={reduced} onChange={(e) => setReduced(e.target.checked)} /> Reduced motion</label>
    </div>
  );
}

function IotPanel({ apiBase, planId, vehicleId }: { apiBase: string; planId: number | null; vehicleId: number | string | null }) {
  const [readings, setReadings] = useState<SensorReading[] | null>(null);
  useEffect(() => {
    setReadings(null);
    if (vehicleId === null || planId === null) return;
    let live = true;
    void Vis.fetchSensorReadings(apiBase, `${planId}:${vehicleId}`).then((r) => { if (live) setReadings(r); });
    return () => { live = false; };
  }, [apiBase, planId, vehicleId]);

  if (vehicleId === null) return <p className="muted">Select a vehicle to check for live sensor readings.</p>;
  if (readings === null) return <p className="muted">Checking for sensor readings{"…"}</p>;
  if (!readings.length) return <p className="muted">No sensor readings received for Vehicle {vehicleId} on this plan yet (pool id <code>{planId}:{vehicleId}</code>). This is not simulated data {"—"} it stays empty until a real ESP32 reading is POSTed.</p>;
  const latest = readings[readings.length - 1];
  return (
    <>
      <div className="check-row"><span className="data-tag live">LIVE</span> Latest reading, t={fmt(latest.timestamp, 2)} hr</div>
      <dl><dt>Temperature</dt><dd>{fmt(latest.temperature, 1)}{"°"}C</dd><dt>Humidity</dt><dd>{fmt(latest.humidity, 1)}%</dd><dt>Readings received</dt><dd>{readings.length}</dd></dl>
    </>
  );
}

function Legend({ solution }: { solution: VizSolution | undefined }) {
  if (!solution) return null;
  const used = solution.vehicles.filter((v) => v.used).slice(0, 8);
  const rgb = (c: number[]) => `rgb(${c.join(",")})`;
  return (
    <>
      {used.map((v) => <div className="legend-row" key={String(v.id)}><span className="swatch" style={{ background: Vis.colorForIdCss(v.id) }} />Vehicle {v.id}</div>)}
      <div className="legend-row"><span className="swatch" style={{ background: rgb(Vis.STATUS_COLORS.unserved) }} />Unserved farmer</div>
      {!!solution.farmgateFarmerIds?.length && <div className="legend-row"><span className="swatch" style={{ background: rgb(Vis.STATUS_COLORS.farmgate) }} />Sold at farm gate</div>}
      <div className="legend-row"><span className="swatch" style={{ background: rgb(Vis.MARKET_COLOR) }} />Market</div>
    </>
  );
}

export function MapView({ visible, go }: { visible: boolean; go: (v: ViewName) => void }) {
  const { state, actions } = useApp();
  const plan = state.plan;
  const [ui, setUiRaw] = useState<Ui>(initialUi);
  const uiRef = useRef(ui);
  uiRef.current = ui;
  const setUi = useCallback((p: Partial<Ui>) => { uiRef.current = { ...uiRef.current, ...p }; setUiRaw(uiRef.current); }, []);

  const [speed, setSpeedState] = useState(() => Number(store.get("fpoSimSpeed")) || 2);
  const [reduced, setReducedState] = useState(() => {
    const saved = store.get("fpoReducedMotion");
    if (saved !== null) return saved === "1";
    return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const slotRef = useRef<HTMLDivElement>(null);
  const storyEl = useRef<HTMLDivElement>(null);
  const detailsEl = useRef<HTMLDivElement>(null);
  const compareEl = useRef<HTMLDivElement>(null);

  const mapRef = useRef<MapController | null>(null);
  const engineRef = useRef<SimEngine | null>(null);
  const storyRef = useRef<Story | null>(null);
  const theaterRef = useRef<Theater | null>(null);

  const solution = (): VizSolution | undefined => uiRef.current.payload?.solutions[uiRef.current.algo];

  // ---- engine tick: drive the map, story and (for a selected vehicle) the details panel ----
  const onTick = useCallback((snap: EngineSnapshot) => {
    const map = mapRef.current;
    if (map) {
      map.setVehiclePositions(snap.vehiclePositions);
      map.setVisitedSets(snap.visitedFarmerIds, snap.visitedMarketIds, snap.visitedGeneration);
    }
    storyRef.current?.applyTime(snap.t);
    const sel = uiRef.current.selection;
    if (sel && sel.type === "vehicle" && detailsEl.current) Vis.renderDetailsPanel(detailsEl.current, sel, solution(), snap);
  }, []);

  const syncMode = useCallback(() => {
    const m = mapRef.current;
    if (m) setUi({ mode3d: !!m.mode3d, chase: !!m.follow });
  }, [setUi]);

  // ---- stage tabs: stage 6 plays, stage 7 jumps to the end, the rest pause ----
  const setStage = useCallback((stage: number) => {
    setUi({ stage });
    mapRef.current?.setStage(stage);
    const e = engineRef.current;
    if (e) {
      if (stage === 6 && !reduced) e.play();
      else if (stage === 7) { e.pause(); e.seek(e.maxT); }
      else e.pause();
    }
  }, [setUi, reduced]);

  // ---- put a solution on the map and (re)build the engine + story ----
  const applySolution = useCallback((payload: VizPayload, algo: string, stage: number) => {
    const sol = payload.solutions[algo];
    const map = mapRef.current;
    if (!map || !sol) return;
    map.setSolution(sol);
    engineRef.current?.pause();
    const engine = new Vis.SimulationEngine(sol.simulationEvents, sol.routes);
    engine.setSpeed(speed);
    engine.on(onTick);
    engineRef.current = engine;
    if (storyEl.current) {
      storyRef.current = new Vis.StoryTimeline(storyEl.current, Vis.buildNarrative(sol), {
        onStepClick: (step) => { engine.pause(); engine.seek(step.t); },
      });
      storyRef.current.applyTime(engine.t);
    }
    if (detailsEl.current) Vis.renderDetailsPanel(detailsEl.current, null, null, null);
    setUi({ selection: null, engineKey: uiRef.current.engineKey + 1 });
    setStage(stage);
  }, [onTick, setStage, setUi, speed]);

  // ---- 1) create the map the first time the tab is shown (MapLibre needs a laid-out container) ----
  const [wantInit, setWantInit] = useState(visible);
  useEffect(() => { if (visible) setWantInit(true); }, [visible]);
  useEffect(() => {
    if (!wantInit) return;
    let cancelled = false;
    let map: MapController | null = null;
    let initP: Promise<void> | null = null;
    // deferred a tick so React StrictMode's dev-only mount/unmount/mount never builds two maps
    const timer = window.setTimeout(() => {
      map = new Vis.LogisticsMap(containerRef.current!);
      map.onSelect = (type, id, object) => { setUi({ selection: { type, id, object }, sidePane: "details" }); };
      map.onMapError = (msg) => setUi({ note: msg });
      initP = map.init().then(() => {
        if (cancelled || !map) return;
        mapRef.current = map;
        const overlay = overlayRef.current!;
        const q = (id: string) => overlay.querySelector<HTMLElement>("#" + id)!;
        theaterRef.current = new Vis.TheaterMode({
          overlayEl: overlay, mapSlotEl: slotRef.current!, map, legendEl: legendRef.current,
          getSolution: solution, getEngine: () => engineRef.current,
          onClose: () => { engineRef.current?.seek(engineRef.current.t); syncMode(); },
          on3DChange: syncMode,
          els: {
            caption: q("theaterCaption"), prevBtn: q("theaterPrevBtn"), nextBtn: q("theaterNextBtn"), exitBtn: q("theaterExitBtn"),
            freeLookBtn: q("theaterFreeLookBtn"), view3dBtn: q("theater3dBtn"), chaseBtn: q("theaterChaseBtn"),
            followLabel: q("theaterFollowLabel"), progressText: q("theaterProgressText"), progressFill: q("theaterProgressFill"),
          },
        });
        setUi({ ready: true });
      }).catch((err: Error) => { console.error(err); if (!cancelled) setUi({ error: `Couldn’t set up the map: ${err.message}` }); });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      engineRef.current?.pause();
      const m = map;
      mapRef.current = null; theaterRef.current = null;
      if (m) void (initP ?? Promise.resolve()).finally(() => { try { m.destroy(); } catch { /* ignore */ } });
      setUi({ ready: false, loadedPlanId: null });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantInit]);

  // MapLibre does not observe its container, so re-measure whenever the tab becomes visible again.
  useEffect(() => {
    if (!visible) return;
    const id = requestAnimationFrame(() => mapRef.current?.resize());
    return () => cancelAnimationFrame(id);
  }, [visible, ui.ready]);

  // ---- 2) load the visualization for the current plan ----
  const loadPlan = useCallback(async (planId: number) => {
    setUi({ loading: true, error: "" });
    try {
      const payload = await Vis.fetchVisualization(state.apiBase, planId);
      const algo = payload.solutions[uiRef.current.algo] ? uiRef.current.algo : ILO;
      setUi({ payload, algo, loadedPlanId: planId, loading: false, compareOn: false });
      applySolution(payload, algo, 1);
      setUi({ sidePane: "story" });
    } catch (err) {
      setUi({ loading: false, error: err instanceof Error ? err.message : String(err) });
    }
  }, [applySolution, setUi, state.apiBase]);

  useEffect(() => {
    if (!ui.ready || !visible) return;
    if (!plan) {
      if (ui.loadedPlanId !== null) {
        engineRef.current?.pause(); engineRef.current = null; storyRef.current = null;
        storyEl.current?.replaceChildren();
        setUi({ payload: null, loadedPlanId: null, selection: null, compareOn: false, error: "", engineKey: uiRef.current.engineKey + 1 });
      }
      return;
    }
    if (ui.loadedPlanId !== plan.id) void loadPlan(plan.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ui.ready, visible, plan?.id]);

  // ---- details / compare panels (imperative renderers from the engine) ----
  useEffect(() => {
    if (detailsEl.current && ui.payload) Vis.renderDetailsPanel(detailsEl.current, ui.selection, solution(), engineRef.current?.snapshot() ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ui.selection]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ui.payload) return;
    if (ui.compareOn) {
      if (compareEl.current) Vis.renderComparisonPanel(compareEl.current, ui.payload.solutions);
      map.setCompareSolution(ui.payload.solutions[compareAlgoFor(ui.algo)] ?? null);
    } else {
      map.setCompareSolution(null);
    }
  }, [ui.compareOn, ui.payload, ui.algo, ui.engineKey]);

  // ---- speed / reduced motion ----
  const setSpeed = (n: number) => { setSpeedState(n); store.set("fpoSimSpeed", String(n)); engineRef.current?.setSpeed(n); };
  const setReduced = (b: boolean) => { setReducedState(b); store.set("fpoReducedMotion", b ? "1" : "0"); if (b) engineRef.current?.pause(); };

  // ---- toolbar actions ----
  const switchAlgo = (algo: string) => {
    setUi({ algo });
    const payload = uiRef.current.payload;
    if (payload) applySolution(payload, algo, uiRef.current.stage);
  };
  const toggle3D = () => {
    const m = mapRef.current; if (!m) return;
    const on = !m.mode3d;
    m.set3D(on);
    if (!on && m.follow) m.setFollow(null);
    syncMode();
  };
  // Third-person chase camera (3D): follows the selected vehicle, else whichever vehicle is on the road.
  const toggleChase = () => {
    const m = mapRef.current; if (!m) return;
    if (m.follow) { m.setFollow(null); syncMode(); return; }
    if (!m.mode3d) m.set3D(true);
    const sel = uiRef.current.selection;
    m.setFollow({ mode: "chase", vehicleId: sel && sel.type === "vehicle" ? sel.id : undefined, zoom: 17.1 });
    syncMode();
  };

  // ---- keyboard: space play/pause, arrows scrub, 1-7 stages ----
  useEffect(() => {
    if (!visible) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (/^(INPUT|SELECT|TEXTAREA|BUTTON|SUMMARY|A)$/.test(t.tagName) || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey || theaterRef.current?.isOpen) return;
      const engine = engineRef.current;
      if (!engine) return;
      if (e.key === " ") {
        e.preventDefault();
        if (reduced) return;
        if (engine.playing) engine.pause(); else engine.play();
      } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        engine.pause();
        engine.seekProgress(Math.min(1, Math.max(0, engine.progress + (e.key === "ArrowRight" ? 0.02 : -0.02))));
      } else if (/^[1-7]$/.test(e.key)) {
        setStage(Number(e.key));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, reduced, setStage]);

  const sol = ui.payload?.solutions[ui.algo];
  const hasPlan = !!ui.payload;
  const emptyTitle = ui.error ? "Couldn’t load the plan" : "No plan on the map";
  const emptyText = ui.error || (state.plan ? "Loading the plan…" : "Run a scenario from the Scenarios tab, or compute a plan, then it appears here.");

  return (
    <>
      <StaleBanner busy={state.planStatus === "computing"} onRecompute={() => void actions.computePlan()} />
      <div className="map-bar">
        <label className="sr-only" htmlFor="mapAlgoSelect">Algorithm shown on the map</label>
        <select id="mapAlgoSelect" className="algo-select" value={ui.algo} disabled={!hasPlan} onChange={(e) => switchAlgo(e.target.value)}>
          {ALGO_OPTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <button id="mapCompareToggle" className={"btn " + (ui.compareOn ? "btn-primary" : "btn-secondary")} aria-pressed={ui.compareOn} title="Compare mode" disabled={!hasPlan} onClick={() => setUi({ compareOn: !ui.compareOn })}><Icon name="split" /><span>Compare mode</span></button>
        <button id="map3dToggle" className={"btn " + (ui.mode3d ? "btn-primary" : "btn-secondary")} aria-pressed={ui.mode3d} title="3D view" disabled={!ui.ready} onClick={toggle3D}><Icon name="cube" /><span>3D</span></button>
        <button id="mapChaseToggle" className={"btn " + (ui.chase ? "btn-primary" : "btn-secondary")} aria-pressed={ui.chase} title="3D third-person camera behind a moving truck" disabled={!hasPlan} onClick={toggleChase}><Icon name="truck" /><span>Chase cam</span></button>
        <span className="grow" />
        <button id="mapRefreshBtn" className="btn btn-secondary" disabled={!plan || ui.loading || !ui.ready} onClick={() => plan && void loadPlan(plan.id)}>{ui.loading ? "Loading…" : "Reload plan"}</button>
        <button id="theaterOpenBtn" className="btn btn-primary theater-open-btn" disabled={!hasPlan} onClick={() => containerRef.current && theaterRef.current?.open(containerRef.current)}><Icon name="present" /><span>Watch the walkthrough</span></button>
      </div>

      <div className="map-grid">
        <div className="map-col">
          {/* The map container is reparented by the theater, so these siblings are always rendered (never mounted/unmounted). */}
          <div className="map-main">
            <div id="mapContainer" className="map-canvas" ref={containerRef} />
            <div id="mapEmptyState" className="map-empty" hidden={hasPlan}>
              <div>
                <h2>{emptyTitle}</h2>
                <p>{emptyText}</p>
                {!state.plan && <button className="btn btn-primary" type="button" onClick={() => go("start")}>Go to scenarios<Icon name="arrow" /></button>}
              </div>
            </div>
            <div id="mapLegend" className="map-legend" ref={legendRef}><Legend solution={sol} /></div>
            <p className="map-note" hidden={!ui.note}>{ui.note}</p>
            <div className="map-busy" role="status" hidden={!(ui.loading || (!ui.ready && !ui.error))}><span className="spinner" aria-hidden="true" />{ui.ready ? "Loading plan…" : "Starting the map…"}</div>
          </div>

          <Transport key={ui.engineKey} engine={engineRef.current} speed={speed} setSpeed={setSpeed} reduced={reduced} setReduced={setReduced} onPlayChange={() => undefined} />
          <p className="kbd-hint" aria-hidden="true"><kbd>Space</kbd> play/pause <kbd>{"←"}</kbd><kbd>{"→"}</kbd> scrub <kbd>1</kbd>{"–"}<kbd>7</kbd> stages</p>

          <div className="stage-rail">
            <div className="stage-tabs" id="stageTabs" role="group" aria-label="Presentation stage">
              {STAGES.map((label, i) => (
                <button key={label} className={"stage-tab" + (ui.stage === i + 1 ? " active" : "") + (ui.stage > i + 1 ? " done" : "")} aria-pressed={ui.stage === i + 1} disabled={!hasPlan} onClick={() => setStage(i + 1)}><b>{i + 1}</b>{label}</button>
              ))}
            </div>
            <p id="stageBlurb" className="stage-blurb">{Vis.STAGE_BLURBS[ui.stage] || ""}</p>
          </div>
        </div>

        <aside className="side" aria-label="Plan explanation">
          <div className="seg" role="tablist" id="sideTabs">
            {(["story", "details"] as const).map((p) => (
              <button key={p} role="tab" className={"seg-btn" + (ui.sidePane === p ? " active" : "")} aria-selected={ui.sidePane === p} onClick={() => setUi({ sidePane: p })}>{p === "story" ? "Story" : "Details"}</button>
            ))}
          </div>
          <div className="side-pane" id="sidePane-story" hidden={ui.sidePane !== "story"}>
            <p className="hint">What happens, in order. Select a line to jump the simulation there.</p>
            <div id="storyPanel" className="story-panel" ref={storyEl} />
            {!hasPlan && <p className="hint">Load a plan to see the story.</p>}
          </div>
          <div className="side-pane" id="sidePane-details" hidden={ui.sidePane !== "details"}>
            <div id="detailsPanel" ref={detailsEl} />
            {!hasPlan && <p className="hint">Select a farmer, vehicle, market or route on the map.</p>}
            <h3 className="side-sub">Live sensors</h3>
            <div id="iotPanel"><IotPanel apiBase={state.apiBase} planId={ui.payload?.id ?? null} vehicleId={ui.selection?.type === "vehicle" ? ui.selection.id : null} /></div>
          </div>
        </aside>
      </div>

      <div id="compareMetricsPanel" className="sec" style={{ display: ui.compareOn && hasPlan ? "" : "none" }}>
        <div className="sec-head"><h2>Baseline vs optimized</h2></div>
        <div id="compareMetricsBody" className="tablewrap" ref={compareEl} />
      </div>

      {/* THEATER: fullscreen presentation of the loaded plan. Sibling of the map view, so tab switching never hides it. */}
      <div id="theaterOverlay" className="theater-overlay" hidden role="dialog" aria-modal="true" aria-label="Plan walkthrough" ref={overlayRef}>
        <div className="theater-box">
          <div className="theater-topbar">
            <div className="theater-topbar-left">
              <span id="theaterProgressText" className="theater-progress-text">Step 1 of 1</span>
              <span id="theaterFollowLabel" className="theater-follow" hidden />
            </div>
            <div className="theater-topbar-actions">
              <button id="theater3dBtn" type="button" className="theater-chip">3D: Off</button>
              <button id="theaterChaseBtn" type="button" className="theater-chip">Chase cam: Off</button>
              <button id="theaterFreeLookBtn" type="button" className="theater-chip">Free look: Off</button>
              <button id="theaterExitBtn" type="button" className="theater-chip theater-chip--exit"><Icon name="close" />Exit</button>
            </div>
          </div>
          <div className="theater-progressbar"><div id="theaterProgressFill" /></div>
          <div id="theaterMapSlot" className="theater-map-slot" ref={slotRef} />
          <div className="theater-caption-bar"><div id="theaterCaption" className="theater-caption" /></div>
          <div className="theater-controls">
            <button id="theaterPrevBtn" type="button" className="theater-nav-btn"><Icon name="prev" small={false} />Back</button>
            <button id="theaterNextBtn" type="button" className="theater-nav-btn theater-nav-btn--primary">Next<Icon name="next" small={false} /></button>
          </div>
        </div>
      </div>
    </>
  );
}
