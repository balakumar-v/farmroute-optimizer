// frontend/vis/mapview.js
// -------------------------------------------------------------------------
// Glue code for the "Map & simulation" tab. Owns no optimization or
// simulation logic itself -- it wires together Vis.LogisticsMap (the map),
// Vis.SimulationEngine (the timeline), Vis.renderDetailsPanel/renderComparisonPanel
// (the side panels), and the DOM controls in index.html's #view-map section.
(function () {
  "use strict";
  const Vis = (window.Vis = window.Vis || {});

  const el = (id) => document.getElementById(id);

  const view = {
    initialized: false,
    map: null,
    engine: null,
    story: null,
    theater: null,
    vizPayload: null, // full GET /plan/{id}/visualization response
    currentAlgo: "integrated_logistics_optimization",
    compareAlgo: "individual_transport",
    compareOn: false,
    stage: 1,
    selection: null,
    stalePlanNotice: false,
  };

  function fmt(n, digits) {
    if (n === undefined || n === null || Number.isNaN(n)) return "\u2013";
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 1 : digits });
  }

  function currentSolution() {
    return view.vizPayload && view.vizPayload.solutions[view.currentAlgo];
  }
  function compareSolution() {
    return view.vizPayload && view.compareOn ? view.vizPayload.solutions[view.compareAlgo] : null;
  }

  function pickDefaultCompareAlgo() {
    return view.currentAlgo === "integrated_logistics_optimization" ? "individual_transport" : "integrated_logistics_optimization";
  }

  // ---- empty / error state over the map ----------------------------------------
  function showMapEmpty(title, message) {
    const safe = String(message).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    el("mapEmptyState").hidden = false;
    el("mapEmptyState").innerHTML =
      `<div><h2>${title}</h2><p>${safe}</p><button class="btn btn-primary" type="button" data-goto="start">Go to scenarios</button></div>`;
  }

  // ---- legend --------------------------------------------------------------
  function renderLegend() {
    const sol = currentSolution();
    const legend = el("mapLegend");
    if (!sol) { legend.innerHTML = ""; return; }
    const usedVehicles = sol.vehicles.filter((v) => v.used).slice(0, 8);
    let html = "";
    for (const v of usedVehicles) {
      html += `<div class="legend-row"><span class="swatch" style="background:${Vis.colorForIdCss(v.id)}"></span>Vehicle ${v.id}</div>`;
    }
    const u = Vis.STATUS_COLORS.unserved, mk = Vis.MARKET_COLOR;
    html += `<div class="legend-row"><span class="swatch" style="background:rgb(${u.join(",")})"></span>Unserved farmer</div>`;
    if (sol.farmgateFarmerIds && sol.farmgateFarmerIds.length) {
      const g = Vis.STATUS_COLORS.farmgate;
      html += `<div class="legend-row"><span class="swatch" style="background:rgb(${g.join(",")})"></span>Sold at farm gate</div>`;
    }
    html += `<div class="legend-row"><span class="swatch" style="background:rgb(${mk.join(",")})"></span>Market</div>`;
    legend.innerHTML = html;
  }

  // ---- IoT panel (section 16) ------------------------------------------------
  async function renderIotForVehicle(vehicleId) {
    const container = el("iotPanel");
    const planId = view.vizPayload.id;
    const poolId = `${planId}:${vehicleId}`;
    const apiBase = window.FPO.getApiBase();
    const readings = await Vis.fetchSensorReadings(apiBase, poolId);
    if (!readings.length) {
      container.innerHTML = `<p class="muted">No sensor readings received for Vehicle ${vehicleId} on this plan yet (pool id <code>${poolId}</code>). This is not simulated data \u2014 it stays empty until a real ESP32 reading is POSTed.</p>`;
      return;
    }
    const latest = readings[readings.length - 1];
    container.innerHTML = `
      <div class="check-row"><span class="data-tag live">LIVE</span> Latest reading, t=${fmt(latest.timestamp, 2)} hr</div>
      <dl>
        <dt>Temperature</dt><dd>${fmt(latest.temperature, 1)}\u00b0C</dd>
        <dt>Humidity</dt><dd>${fmt(latest.humidity, 1)}%</dd>
        <dt>Readings received</dt><dd>${readings.length}</dd>
      </dl>`;
  }
  function resetIotPanel() {
    el("iotPanel").innerHTML = `<p class="muted">Select a vehicle to check for live sensor readings.</p>`;
  }

  // ---- selection -------------------------------------------------------------
  function handleSelect(type, id, object) {
    view.selection = { type, id, object };
    Vis.renderDetailsPanel(el("detailsPanel"), view.selection, currentSolution(), view.engine ? view.engine.snapshot() : null);
    if (type === "vehicle") renderIotForVehicle(id); else resetIotPanel();
    if (window.FPO.showSidePane) window.FPO.showSidePane("details");
  }

  // ---- stage tabs (section 10) ------------------------------------------------
  function setStage(stage) {
    view.stage = stage;
    document.querySelectorAll("#stageTabs .stage-tab").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.dataset.stage) === stage);
      btn.classList.toggle("done", Number(btn.dataset.stage) < stage);
    });
    el("stageBlurb").textContent = Vis.STAGE_BLURBS[stage] || "";
    if (view.map) view.map.setStage(stage);
    if (view.engine) {
      if (stage === 6) {
        view.engine.play();
      } else if (stage === 7) {
        view.engine.pause();
        view.engine.seek(view.engine.maxT);
      } else {
        view.engine.pause();
      }
      syncTimelineUI();
    }
  }

  // ---- timeline (section 14) --------------------------------------------------
  function syncTimelineUI() {
    const snap = view.engine.snapshot();
    el("simPlayBtn").innerHTML = snap.playing
      ? '<svg class="i i-sm"><use href="#i-pause"/></svg><span>Pause</span>'
      : '<svg class="i i-sm"><use href="#i-play"/></svg><span>Play</span>';
    el("simTimeReadout").textContent = `t = ${fmt(snap.t, 2)} hr`;
    const scrubber = el("simScrubber");
    if (document.activeElement !== scrubber) {
      scrubber.value = String(Math.round(view.engine.progress * 1000));
    }
  }

  function sync3DButtons() {
    const on = !!view.map.mode3d;
    el("map3dToggle").classList.toggle("btn-primary", on);
    el("map3dToggle").classList.toggle("btn-secondary", !on);
    const chase = !!view.map.follow;
    el("mapChaseToggle").classList.toggle("btn-primary", chase);
    el("mapChaseToggle").classList.toggle("btn-secondary", !chase);
    el("map3dToggle").setAttribute("aria-pressed", String(on));
    el("mapChaseToggle").setAttribute("aria-pressed", String(chase));
  }

  function onEngineTick(snapshot) {
    view.map.setVehiclePositions(snapshot.vehiclePositions);
    view.map.setVisitedSets(snapshot.visitedFarmerIds, snapshot.visitedMarketIds, snapshot.visitedGeneration);
    syncTimelineUI();
    if (view.story) view.story.applyTime(snapshot.t);
    if (view.selection && view.selection.type === "vehicle") {
      Vis.renderDetailsPanel(el("detailsPanel"), view.selection, currentSolution(), snapshot);
    }
  }

  // ---- step-by-step story (section: "Step-by-step story" card) ---------------
  function rebuildStory() {
    const steps = Vis.buildNarrative(currentSolution());
    view.story = new Vis.StoryTimeline(el("storyPanel"), steps, {
      onStepClick: (step) => {
        view.engine.pause();
        view.engine.seek(step.t);
        syncTimelineUI();
      },
    });
    view.story.applyTime(view.engine.t);
  }

  function wireTimelineControls() {
    el("simPlayBtn").addEventListener("click", () => {
      if (el("simReducedMotion").checked) return; // reduced motion: scrubbing only, see below
      if (view.engine.playing) view.engine.pause(); else view.engine.play();
      syncTimelineUI();
    });
    el("simResetBtn").addEventListener("click", () => { view.engine.reset(); });
    el("simSpeedSelect").addEventListener("change", (e) => view.engine.setSpeed(Number(e.target.value)));
    el("simScrubber").addEventListener("input", (e) => {
      view.engine.pause();
      view.engine.seekProgress(Number(e.target.value) / 1000);
      syncTimelineUI();
    });
    el("simReducedMotion").addEventListener("change", (e) => {
      const disabled = e.target.checked;
      el("simPlayBtn").disabled = disabled;
      el("simSpeedSelect").disabled = disabled;
      if (disabled) view.engine.pause();
      syncTimelineUI();
    });
  }

  // ---- compare mode (section 12) ------------------------------------------------
  function refreshCompareUI() {
    const panel = el("compareMetricsPanel");
    if (!view.compareOn || !view.vizPayload) {
      panel.style.display = "none";
      if (view.map) view.map.setCompareSolution(null);
      return;
    }
    panel.style.display = "";
    Vis.renderComparisonPanel(el("compareMetricsBody"), view.vizPayload.solutions);
    view.map.setCompareSolution(compareSolution());
  }

  // ---- loading a plan ------------------------------------------------------------
  async function loadLatestPlan() {
    const btn = el("mapRefreshBtn");
    const DEFAULT_LABEL = "Load latest plan";
    btn.disabled = true;
    btn.textContent = "Loading\u2026";
    el("theaterOpenBtn").disabled = true; // re-enabled below only once a plan actually loads
    try {
      const apiBase = window.FPO.getApiBase();
      const planId = window.FPO.getLastPlanId();
      if (planId === null) {
        showMapEmpty("No plan on the map", "Nothing has been computed yet. Run a scenario, or compute a plan from the Plan tab.");
        return;
      }
      const payload = await Vis.fetchVisualization(apiBase, planId);
      view.vizPayload = payload;
      view.stalePlanNotice = false;
      if (!view.vizPayload.solutions[view.currentAlgo]) {
        view.currentAlgo = "integrated_logistics_optimization";
      }
      view.compareAlgo = pickDefaultCompareAlgo();
      el("mapEmptyState").hidden = true;

      view.map.setSolution(currentSolution());
      view.engine = new Vis.SimulationEngine(currentSolution().simulationEvents, currentSolution().routes);
      view.engine.on(onEngineTick);
      rebuildStory();
      renderLegend();
      view.selection = null;
      Vis.renderDetailsPanel(el("detailsPanel"), null, null, null);
      resetIotPanel();
      refreshCompareUI();
      setStage(1);
      syncTimelineUI();
      if (window.FPO.showSidePane) window.FPO.showSidePane("story");
      el("theaterOpenBtn").disabled = false;
    } catch (err) {
      showMapEmpty("Couldn't load the plan", err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = DEFAULT_LABEL;
      btn.classList.remove("btn-primary");
      btn.classList.add("btn-secondary");
    }
  }

  function switchAlgo(algoKey) {
    view.currentAlgo = algoKey;
    if (!view.vizPayload) return;
    view.compareAlgo = pickDefaultCompareAlgo();
    view.map.setSolution(currentSolution());
    view.engine.pause();
    view.engine = new Vis.SimulationEngine(currentSolution().simulationEvents, currentSolution().routes);
    view.engine.on(onEngineTick);
    rebuildStory();
    renderLegend();
    view.selection = null;
    Vis.renderDetailsPanel(el("detailsPanel"), null, null, null);
    resetIotPanel();
    refreshCompareUI();
    setStage(view.stage); // keep the user's current stage, just re-applied to the new solution
  }

  // ---- wiring ------------------------------------------------------------------
  async function ensureInitialized() {
    if (view.initialized) return;
    view.initialized = true;

    view.map = new Vis.LogisticsMap(el("mapContainer"));
    view.map.onSelect = handleSelect;
    view.map.onMapError = (msg) => {
      const note = document.createElement("p");
      note.className = "map-note";
      note.textContent = msg;
      el("mapContainer").parentElement.appendChild(note);
    };
    await view.map.init();

    view.theater = new Vis.TheaterMode({
      overlayEl: el("theaterOverlay"),
      mapSlotEl: el("theaterMapSlot"),
      map: view.map,
      legendEl: el("mapLegend"),
      getSolution: currentSolution,
      getEngine: () => view.engine,
      onClose: () => {
        // the theater drove vehicle/visited state itself; put the main tab's
        // engine-derived state back
        if (view.engine) view.engine.seek(view.engine.t);
        syncTimelineUI();
        sync3DButtons();
      },
      on3DChange: () => sync3DButtons(),
      els: {
        caption: el("theaterCaption"),
        prevBtn: el("theaterPrevBtn"),
        nextBtn: el("theaterNextBtn"),
        exitBtn: el("theaterExitBtn"),
        freeLookBtn: el("theaterFreeLookBtn"),
        view3dBtn: el("theater3dBtn"),
        chaseBtn: el("theaterChaseBtn"),
        followLabel: el("theaterFollowLabel"),
        progressText: el("theaterProgressText"),
        progressFill: el("theaterProgressFill"),
      },
    });
    el("theaterOpenBtn").addEventListener("click", () => view.theater.open(el("mapContainer")));

    document.querySelectorAll("#stageTabs .stage-tab").forEach((btn) => {
      btn.addEventListener("click", () => setStage(Number(btn.dataset.stage)));
    });
    wireTimelineControls();

    el("mapAlgoSelect").addEventListener("change", (e) => switchAlgo(e.target.value));
    el("mapCompareToggle").addEventListener("click", () => {
      view.compareOn = !view.compareOn;
      el("mapCompareToggle").classList.toggle("btn-primary", view.compareOn);
      el("mapCompareToggle").classList.toggle("btn-secondary", !view.compareOn);
      el("mapCompareToggle").setAttribute("aria-pressed", String(view.compareOn));
      refreshCompareUI();
    });
    el("map3dToggle").addEventListener("click", () => {
      const on = !view.map.mode3d;
      view.map.set3D(on);
      if (!on && view.map.follow) view.map.setFollow(null);
      sync3DButtons();
    });
    // Third-person chase camera (3D): follows the selected vehicle, else
    // whichever vehicle is currently on the road.
    el("mapChaseToggle").addEventListener("click", () => {
      if (view.map.follow) { view.map.setFollow(null); sync3DButtons(); return; }
      if (!view.map.mode3d) view.map.set3D(true);
      const sel = view.selection && view.selection.type === "vehicle" ? view.selection.id : undefined;
      view.map.setFollow({ mode: "chase", vehicleId: sel, zoom: 17.1 });
      sync3DButtons();
    });
    el("mapRefreshBtn").addEventListener("click", loadLatestPlan);

    await loadLatestPlan();
  }

  // Activate on first switch to the Map tab (MapLibre needs a laid-out,
  // visible container to size its canvas correctly -- initializing while
  // the tab is display:none would give it a 0x0 canvas).
  document.getElementById("tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn && btn.dataset.view === "map") {
      ensureInitialized().catch((err) => {
        console.error(err);
        showMapEmpty("Couldn't set up the map", err.message);
      });
    }
  });

  // If a plan is computed on another tab while this one has already been
  // opened once, don't silently rebuild the map underneath an
  // in-progress simulation/selection -- just offer a refresh.
  window.FPO.onPlanComputed = function () {
    if (!view.initialized) return;
    const btn = el("mapRefreshBtn");
    btn.textContent = "New plan available \u2014 reload";
    btn.classList.add("btn-primary");
  };

  // Read-only introspection hook for debugging/testing -- not used by any
  // production code path above.
  window.FPO.mapview = view;
  // Hooks for app.js: open the map from another tab, and re-measure it after a tab switch.
  window.FPO.ensureMapReady = function () {
    return ensureInitialized().catch((err) => {
      console.error(err);
      showMapEmpty("Couldn't set up the map", err.message);
    });
  };
  window.FPO.resizeMap = function () {
    if (view.map && view.map.map) view.map.map.resize();
  };
})();
