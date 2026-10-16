import maplibregl from "maplibre-gl";
import * as deck from "./deckApi.js";
// frontend/vis/logisticsMap.js
// -------------------------------------------------------------------------
// MapLibre GL JS provides the interactive base map/camera; deck.gl renders
// every data layer on top via a MapboxOverlay (interleaved, per the brief's
// "follow the current official integration approach rather than a custom
// WebGL overlay"). No React: this project's frontend is plain HTML/CSS/JS
// with no build step (see README.md / frontend/app.js), so this uses
// deck.gl's core (non-React) layer classes directly -- introducing React
// here just for this one tab would mean introducing a bundler too, which
// rule 20.12 of the brief explicitly says not to do.
//
// This file only draws what solution/route/simulation data it's given. It
// contains no optimization, pooling, or routing logic of its own.
import { Vis } from "./namespace.js";

  // One flag set per presentation stage (see the brief's section 10). Each
  // stage only toggles which already-computed layers are visible -- nothing
  // is recomputed between stages.
  const STAGE_VISIBILITY = {
    1: { farmers: true, pooling: false, colored: false, markets: false, routes: false, vehicles: false },
    2: { farmers: true, pooling: true, colored: false, markets: false, routes: false, vehicles: false },
    3: { farmers: true, pooling: true, colored: true, markets: false, routes: false, vehicles: false },
    4: { farmers: true, pooling: true, colored: true, markets: true, routes: false, vehicles: false },
    5: { farmers: true, pooling: false, colored: true, markets: true, routes: true, vehicles: false },
    6: { farmers: true, pooling: false, colored: true, markets: true, routes: true, vehicles: true },
    7: { farmers: true, pooling: false, colored: true, markets: true, routes: true, vehicles: true },
  };
  Vis.STAGE_VISIBILITY = STAGE_VISIBILITY;

  // The base map is built here, not fetched: a limewash ground and a lat/lng
  // graticule that always render (so the map still reads as a survey sheet with
  // no internet), with CARTO raster tiles laid over them when they're reachable.
  // Tile failures are non-fatal; they only mean the grid stays visible.
  function graticuleGeoJSON() {
    const feats = [];
    const line = (a, b, k) => feats.push({ type: "Feature", properties: { k }, geometry: { type: "LineString", coordinates: [a, b] } });
    const r = (n) => Math.round(n * 10) / 10;
    for (let lat = 6; lat <= 36; lat = r(lat + 0.1)) line([68, lat], [98, lat], Math.abs(lat - Math.round(lat)) < 1e-6 ? "major" : "minor");
    for (let lng = 68; lng <= 98; lng = r(lng + 0.1)) line([lng, 6], [lng, 36], Math.abs(lng - Math.round(lng)) < 1e-6 ? "major" : "minor");
    return { type: "FeatureCollection", features: feats };
  }
  function buildStyle() {
    const css = getComputedStyle(document.documentElement);
    const v = (n, d) => css.getPropertyValue(n).trim() || d;
    const dark = v("--wash", "#e6ecf0").charAt(1) < "5" && v("--wash", "#e6ecf0") !== "#e6ecf0";
    // Keyless by default. CARTO began watermarking keyless raster tiles in Aug 2026, so it's opt-in via config.js.
    const cfg = Vis.config || {};
    const esri = (name) => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${name}/MapServer/tile/{z}/{y}/{x}`;
    const tile = {
      url: cfg.tileUrl || esri(dark ? "World_Dark_Gray_Base" : "World_Light_Gray_Base"),
      attribution: cfg.tileAttribution || (cfg.tileUrl ? "" : "Tiles \u00A9 Esri, HERE, Garmin, OpenStreetMap contributors"),
      maxZoom: cfg.tileMaxZoom || (cfg.tileUrl ? 19 : 16),
    };
    return {
      version: 8,
      glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      sources: {
        graticule: { type: "geojson", data: graticuleGeoJSON() },
        tiles: {
          type: "raster", tileSize: 256, maxzoom: tile.maxZoom,
          tiles: [tile.url],
          attribution: tile.attribution,
        },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": v("--wash", "#e6ecf0") } },
        { id: "grat-minor", type: "line", source: "graticule", minzoom: 8.5, filter: ["==", ["get", "k"], "minor"], paint: { "line-color": v("--ink-3", "#566170"), "line-width": 0.8, "line-opacity": 0.22 } },
        { id: "grat-major", type: "line", source: "graticule", filter: ["==", ["get", "k"], "major"], paint: { "line-color": v("--ink-3", "#566170"), "line-width": 1.3, "line-opacity": 0.5 } },
        { id: "tiles", type: "raster", source: "tiles", paint: { "raster-opacity": 0.95 } },
      ],
    };
  }

  class LogisticsMap {
    constructor(container) {
      this.container = container;
      this.map = null;
      this.overlay = null;
      this.mode3d = false;
      this.stage = 5; // "routes visible, nothing animating yet" is a sensible default view
      this.onSelect = null; // (type, id, object) => void
      this.onMapError = null; // (message) => void

      this.solution = null; // active solution
      this.compareSolution = null; // second solution, only set in compare mode
      this.compareMode = false;
      this.vehiclePositions = [];
      this.visitedFarmerIds = new Set();
      this.visitedMarketIds = new Set();
      this.visitedGeneration = 0;
      this.follow = null; // {mode:'top'|'chase', vehicleId, zoom} -- see setFollow()
      this._followRaf = null;
      this._cam = null;
      this.theaterMode = false; // cinematic color grading + a spotlight glow under active vehicles

      // Layer cache: keyed by a small dependency list per layer group (see
      // _memoLayers below). Without this, _render() rebuilt EVERY layer --
      // including full farmer/route position arrays -- from scratch on
      // every single animation frame during playback, even though only
      // vehicle positions (and which farmers/markets are visited) actually
      // change frame to frame. At n=100 that's unnoticeable; at
      // n=1,000-10,000 it's real per-frame cost for data that hasn't
      // changed. Only the "vehicles" layer (small -- one entry per active
      // vehicle, not per farmer) is genuinely rebuilt every frame now.
      this._layerCache = new Map();

      // Built once, synchronously (plain canvas drawing, no network) --
      // see icons.js. Every icon layer below reuses this same atlas, only
      // varying getIcon/getColor/getPosition per data point.
      this._iconAtlas = Vis.buildIconAtlas();
    }

    // Returns the cached layer array for `key` if every entry in `deps`
    // is === its value from the last call with this key; otherwise calls
    // `factory()`, caches, and returns the fresh result. deps are compared
    // by reference/value (===), never deep-compared -- callers are
    // responsible for passing something (an object reference, a count, a
    // generation counter) that actually changes when the layer should be
    // rebuilt. Returning the SAME cached layer instance (not just
    // equal-looking props) is what lets deck.gl skip re-diffing that
    // layer entirely when passed to overlay.setProps({layers}) again.
    _memoLayers(key, deps, factory) {
      const cached = this._layerCache.get(key);
      if (cached && cached.deps.length === deps.length && cached.deps.every((d, i) => d === deps[i])) {
        return cached.layers;
      }
      const layers = factory();
      this._layerCache.set(key, { deps, layers });
      return layers;
    }

    async init() {
      let styleFailed = false;
      this.map = new maplibregl.Map({
        container: this.container,
        style: buildStyle(),
        center: [84.9, 25.6],
        zoom: 8,
        pitch: 0,
        maxPitch: 80, // default 60 is too shallow for the 3D chase camera
        attributionControl: { compact: true },
      });
      this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      this.map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

      const loadOrError = new Promise((resolve) => {
        // 'load' also waits for raster tiles, which never settle when offline. The style
        // itself is inline, so 'style.load' is the right moment to attach the overlay.
        let done = false;
        const finish = () => { if (!done) { done = true; resolve(); } };
        this.map.once("style.load", finish);
        this.map.once("load", finish);
        setTimeout(finish, 4000);
        // The style is built in-process and cannot fail to load; what can fail is
        // fetching raster tiles. That's reported once, quietly, and never blocks the map.
        this.map.on("error", (e) => {
          const isTile = e && (e.sourceId === "tiles" || e.tile);
          if (isTile && !styleFailed) {
            styleFailed = true;
            if (this.onMapError) this.onMapError("Offline: street tiles unavailable, showing the grid.");
          } else if (!isTile) {
            console.warn("map error", e && e.error ? e.error : e);
          }
        });
      });
      await loadOrError;

      this.overlay = new deck.MapboxOverlay({ interleaved: true, layers: [] });
      this.map.addControl(this.overlay);
    }

    destroy() {
      if (this.map) this.map.remove();
    }

    // MapLibre needs an explicit resize() after its container's box
    // changes size or moves in the DOM (e.g. theater.js reparenting the
    // map into/out of the fullscreen overlay) -- it doesn't observe that
    // on its own.
    resize() {
      if (this.map) this.map.resize();
    }

    // ---- data wiring -----------------------------------------------------

    setSolution(solution) {
      this._tripVehicle = new Map((solution.routes || []).map((r) => [r.id, r.vehicleId]));
      this.solution = solution;
      this.compareSolution = null;
      this.compareMode = false;
      this.vehiclePositions = [];
      this.visitedFarmerIds = new Set();
      this.visitedMarketIds = new Set();
      this.visitedGeneration = 0;
      this._layerCache.clear(); // new solution -- nothing cached is valid anymore
      this._render();
      this.fitToData();
    }

    setCompareSolution(compareSolution) {
      this.compareSolution = compareSolution;
      this.compareMode = !!compareSolution;
      this._render();
    }

    setStage(stage) {
      this.stage = stage;
      this._render();
    }

    setVehiclePositions(positions) {
      this.vehiclePositions = positions || [];
      this._render();
    }

    setVisitedSets(visitedFarmerIds, visitedMarketIds, generation) {
      this.visitedFarmerIds = visitedFarmerIds || new Set();
      this.visitedMarketIds = visitedMarketIds || new Set();
      // SimulationEngine.snapshot() passes a generation counter that only
      // bumps when the sets' actual content changed (see its docstring).
      // Falling back to bumping our own counter keeps this method safe to
      // call from anywhere that doesn't have an engine-provided one, at
      // the cost of that caller always rebuilding (no memoization).
      this.visitedGeneration = generation === undefined ? this.visitedGeneration + 1 : generation;
      this._render();
    }

    set3D(on) {
      this.mode3d = on;
      this.map.easeTo({ pitch: on ? 55 : 0, duration: 500 });
      this._render();
    }

    // The chase camera shifts the map's vanishing point down via top padding;
    // any non-follow camera move must start from zero padding or the view
    // stays lopsided afterward.
    _clearPadding() {
      const p = this.map.getPadding();
      if (p && (p.top || p.bottom || p.left || p.right)) this.map.setPadding({ top: 0, bottom: 0, left: 0, right: 0 });
    }

    fitToData() {
      if (!this.solution) return;
      this._clearPadding();
      const pts = [
        ...this.solution.farmers.map((f) => [f.lng, f.lat]),
        ...this.solution.markets.map((m) => [m.lng, m.lat]),
      ];
      if (!pts.length) return;
      let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
      for (const [lng, lat] of pts) {
        minLng = Math.min(minLng, lng); maxLng = Math.max(maxLng, lng);
        minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
      }
      this.map.fitBounds([[minLng, minLat], [maxLng, maxLat]], { padding: 56, duration: 400, maxZoom: 13, bearing: 0, pitch: this.mode3d ? 55 : 0 });
    }

    // Cinematic camera for the theater/step-through view: frame exactly the
    // real coordinates a step is "about" (one farmer, one market, a whole
    // route) instead of the wide all-data view fitToData() shows. This is
    // the fix for nearby farmers/vehicles reading as one indistinguishable
    // cluster on the full-extent view -- their real lat/lng never changes,
    // the camera just gets close enough that the same real distance between
    // them now spans many more screen pixels. A single point flies in tight
    // (no bounds to fit); 2+ points fit-bounds with a high maxZoom cap so a
    // pair of very close points doesn't over-zoom into an uninformative
    // close-up. Falls back to the wide fitToData() shot when given no
    // points at all (the story's title/summary bookends).
    flyToPoints(points, opts) {
      opts = opts || {};
      if (!points || !points.length) { this.fitToData(); return; }
      this._clearPadding();
      if (points.length === 1) {
        this.map.flyTo({
          center: [points[0].lng, points[0].lat],
          zoom: opts.zoom || 16,
          bearing: 0, pitch: this.mode3d ? 55 : 0,
          duration: opts.duration === undefined ? 900 : opts.duration,
          essential: true,
        });
        return;
      }
      let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
      for (const p of points) {
        minLng = Math.min(minLng, p.lng); maxLng = Math.max(maxLng, p.lng);
        minLat = Math.min(minLat, p.lat); maxLat = Math.max(maxLat, p.lat);
      }
      this.map.fitBounds([[minLng, minLat], [maxLng, maxLat]], {
        padding: opts.padding === undefined ? 90 : opts.padding,
        maxZoom: opts.maxZoom || 16,
        bearing: 0, pitch: this.mode3d ? 55 : 0,
        duration: opts.duration === undefined ? 900 : opts.duration,
        essential: true,
      });
    }


    // ---- follow camera -----------------------------------------------------
    // 'top'   : keeps the followed vehicle centered at a given zoom.
    // 'chase' : third-person -- camera sits behind the vehicle, looking along
    //           its heading at a steep pitch, with the vehicle in the lower
    //           third of the frame so the road ahead is visible. Meant for 3D
    //           mode (in 2D it degrades to a rotating top-down view).
    // Self-driving: a rAF loop eases the camera toward the target every frame
    // (so it also settles while the sim is paused and follows continuously
    // while positions are updated by whoever owns the timeline). Heading is
    // smoothed with shortest-arc interpolation so a corner turns the camera
    // gradually instead of snapping.
    setFollow(opts, flags) {
      if (this._followRaf) { cancelAnimationFrame(this._followRaf); this._followRaf = null; }
      this.follow = opts || null;
      if (!this.follow) {
        this._setSky(false);
        this._cam = null;
        if (!flags || flags.restore !== false) {
          this.map.easeTo({ bearing: 0, pitch: this.mode3d ? 55 : 0, padding: { top: 0, bottom: 0, left: 0, right: 0 }, duration: 700 });
        }
        return;
      }
      this._setSky(this.follow.mode === "chase");
      const c = this.map.getCenter();
      const pad = this.map.getPadding();
      this._cam = { lng: c.lng, lat: c.lat, zoom: this.map.getZoom(), pitch: this.map.getPitch(), bearing: this.map.getBearing(), padTop: pad.top || 0 };
      const loop = () => {
        if (!this.follow) return;
        this._applyFollow();
        this._followRaf = requestAnimationFrame(loop);
      };
      this._followRaf = requestAnimationFrame(loop);
    }

    // A hazy horizon for the steeply-pitched chase view (otherwise the map
    // just ends in a hard edge against the page background). Best-effort:
    // silently skipped on MapLibre builds/styles without sky support.
    _setSky(on) {
      try {
        if (on) {
          this.map.setSky({
            "sky-color": "#6f8fb0", "horizon-color": "#dfe6ec", "fog-color": "#e6ecf0",
            "sky-horizon-blend": 0.7, "horizon-fog-blend": 0.8, "fog-ground-blend": 0.25,
          });
        } else if (this.map.setSky) {
          this.map.setSky(undefined);
        }
      } catch (e) { /* no sky support -- fine */ }
    }

    _applyFollow() {
      const f = this.follow, cam = this._cam;
      if (!f || !cam) return;
      const v = this.vehiclePositions.find((p) => p.vehicleId === f.vehicleId) || (f.vehicleId === undefined || f.vehicleId === null ? this.vehiclePositions[0] : null);
      if (!v) return;
      const chase = f.mode === "chase";
      const h = this.container.clientHeight || 600;
      const target = chase
        ? { zoom: f.zoom || 17.1, pitch: 67, bearing: v.heading || 0, padTop: h * 0.4 }
        : { zoom: f.zoom || 16, pitch: this.mode3d ? 55 : 0, bearing: 0, padTop: 0 };
      const K_POS = 0.28, K_CAM = 0.09;
      cam.lng += (v.lng - cam.lng) * K_POS;
      cam.lat += (v.lat - cam.lat) * K_POS;
      cam.zoom += (target.zoom - cam.zoom) * K_CAM;
      cam.pitch += (target.pitch - cam.pitch) * K_CAM;
      cam.padTop += (target.padTop - cam.padTop) * K_CAM;
      const d = ((target.bearing - cam.bearing + 540) % 360) - 180; // shortest signed arc
      cam.bearing = (cam.bearing + d * (chase ? 0.12 : K_CAM) + 360) % 360;
      this.map.jumpTo({
        center: [cam.lng, cam.lat], zoom: cam.zoom, pitch: cam.pitch, bearing: cam.bearing,
        padding: { top: cam.padTop, bottom: 0, left: 0, right: 0 },
      });
    }

    // Theater mode: MapLibre's own built-in interaction handlers, each
    // independently enable()/disable()-able. Off by default while the
    // cinematic camera is driving (see theater.js) so a stray scroll/drag
    // doesn't fight the scripted fly-to; the theater's "Free look" toggle
    // flips this back on for viewers who want to explore manually.
    setInteractive(on) {
      const handlers = ["dragPan", "scrollZoom", "boxZoom", "dragRotate", "keyboard", "doubleClickZoom", "touchZoomRotate"];
      for (const h of handlers) {
        if (!this.map[h]) continue;
        if (on) this.map[h].enable(); else this.map[h].disable();
      }
    }

    // Cinematic color grading (CSS filter on the canvas' container) + a
    // soft glow layer under whatever vehicle is currently active -- purely
    // presentational, no effect on solution/status/color logic elsewhere
    // in this file.
    setTheaterMode(on) {
      this.theaterMode = on;
      this.container.classList.toggle("map-canvas--cinematic", on);
      this._render();
    }

    _emitSelect(type, id, object) {
      if (this.onSelect) this.onSelect(type, id, object);
    }

    // ---- layer builders ---------------------------------------------------

    _farmerColor(f, colored) {
      if (f.soldAtFarmGate && !f.served) return [...Vis.STATUS_COLORS.farmgate, 235];
      if (!f.served) return [...Vis.STATUS_COLORS.unserved, 235];
      if (!colored) return [140, 140, 140, 200];
      const vid = this._tripVehicle && this._tripVehicle.get(f.tripId);
      return [...Vis.colorForId(vid !== undefined ? vid : f.tripId), 225];
    }

    _farmerLayer(farmers, colored, visited) {
      // Colored disc (status/trip color + visited ring) unchanged from
      // before -- it owns all picking/click handling, in both 2D and 3D.
      // The flat white plant glyph is only added in 2D; in 3D it's
      // replaced by an actual crate-pile model (_farmerCrateLayer) so we
      // don't end up with a flat icon floating above its own 3D model.
      const disc = new deck.ScatterplotLayer({
        id: "farmers",
        data: farmers,
        getPosition: (f) => [f.lng, f.lat],
        getRadius: 95,
        radiusUnits: "meters",
        radiusMinPixels: 4,
        radiusMaxPixels: 11,
        stroked: true,
        getLineWidth: 1,
        lineWidthMinPixels: 1,
        getLineColor: (f) => (visited.has(f.id) ? [255, 255, 255, 255] : [30, 30, 24, 120]),
        getFillColor: (f) => this._farmerColor(f, colored),
        pickable: true,
        onClick: (info) => info.object && this._emitSelect("farmer", info.object.id, info.object),
      });
      if (this.mode3d) return [disc];
      const icon = new deck.IconLayer({
        id: "farmer-icons",
        data: farmers,
        iconAtlas: this._iconAtlas.atlas,
        iconMapping: this._iconAtlas.mapping,
        getIcon: () => "farmer",
        getPosition: (f) => [f.lng, f.lat],
        getSize: 13,
        sizeUnits: "pixels",
        getColor: [255, 255, 255, 235],
        pickable: false,
      });
      return [disc, icon];
    }

    _farmerCrateLayer(farmers, colored) {
      // A small pile of produce crates per farmer (see models3d.js) instead
      // of a plain extruded cylinder -- reads as "farm produce waiting for
      // pickup" from an oblique 3D angle instead of an abstract post.
      const crates = [];
      for (const f of farmers) {
        for (const c of Vis.farmerFootprints(f.lng, f.lat, f.id)) {
          crates.push({ polygon: c.polygon, elevation: c.height, farmer: f });
        }
      }
      return new deck.PolygonLayer({
        id: "farmer-crates",
        data: crates,
        getPolygon: (d) => d.polygon,
        getElevation: (d) => d.elevation,
        extruded: true,
        wireframe: true,
        getLineColor: [30, 24, 16, 130],
        lineWidthMinPixels: 1,
        getFillColor: (d) => this._farmerColor(d.farmer, colored),
        pickable: true,
        onClick: (info) => info.object && this._emitSelect("farmer", info.object.farmer.id, info.object.farmer),
      });
    }

    _marketLayer(markets, visited) {
      const layers = [
        new deck.ScatterplotLayer({
          id: "markets",
          data: markets,
          getPosition: (m) => [m.lng, m.lat],
          getRadius: 160,
          radiusUnits: "meters",
          radiusMinPixels: 7,
          radiusMaxPixels: 16,
          stroked: true,
          getLineColor: (m) => (visited.has(m.id) ? [255, 255, 255, 255] : [30, 30, 24, 200]),
          lineWidthMinPixels: 2,
          getFillColor: [...Vis.MARKET_COLOR, 245],
          pickable: true,
          onClick: (info) => info.object && this._emitSelect("market", info.object.id, info.object),
        }),
      ];
      if (this.mode3d) return layers;
      layers.push(
        new deck.IconLayer({
          id: "market-icons",
          data: markets,
          iconAtlas: this._iconAtlas.atlas,
          iconMapping: this._iconAtlas.mapping,
          getIcon: () => "market",
          getPosition: (m) => [m.lng, m.lat],
          getSize: 15,
          sizeUnits: "pixels",
          getColor: [255, 255, 255, 235],
          pickable: false,
        }),
        new deck.TextLayer({
          id: "market-labels",
          data: markets,
          getPosition: (m) => [m.lng, m.lat],
          getText: (m) => `M${m.id}`,
          getSize: 11,
          getColor: [30, 30, 24, 255],
          getPixelOffset: [0, -14],
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
        })
      );
      return layers;
    }

    _marketBuildingLayer(markets) {
      // A small two-tier stall (walls + a wider overhanging roof) per
      // market, built in models3d.js. The roof's footprint carries its own
      // base altitude (= wall height) so it floats correctly on top of the
      // walls, rather than a plain extruded cylinder standing for "market".
      const walls = [], roofs = [];
      for (const m of markets) {
        const fp = Vis.marketFootprints(m.lng, m.lat);
        walls.push({ polygon: fp.wall, elevation: fp.wallHeight, market: m });
        roofs.push({ polygon: fp.roof, elevation: fp.roofHeight, market: m });
      }
      return [
        new deck.PolygonLayer({
          id: "market-walls",
          data: walls,
          getPolygon: (d) => d.polygon,
          getElevation: (d) => d.elevation,
          extruded: true,
          wireframe: true,
          getLineColor: [40, 28, 12, 150],
          lineWidthMinPixels: 1,
          getFillColor: [228, 222, 200, 255],
          pickable: true,
          onClick: (info) => info.object && this._emitSelect("market", info.object.market.id, info.object.market),
        }),
        new deck.PolygonLayer({
          id: "market-roofs",
          data: roofs,
          getPolygon: (d) => d.polygon,
          getElevation: (d) => d.elevation,
          extruded: true,
          wireframe: true,
          getLineColor: [60, 38, 10, 180],
          lineWidthMinPixels: 1,
          getFillColor: [...Vis.MARKET_COLOR, 255],
          pickable: true,
          onClick: (info) => info.object && this._emitSelect("market", info.object.market.id, info.object.market),
        }),
        new deck.TextLayer({
          id: "market-labels-3d",
          data: markets,
          getPosition: (m) => [m.lng, m.lat],
          getText: (m) => `M${m.id}`,
          getSize: 12,
          getColor: [255, 255, 255, 255],
          getPixelOffset: [0, -46],
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          fontWeight: 700,
        }),
      ];
    }

    _poolingLayer(routes, colored) {
      const segments = [];
      for (const r of routes) {
        const farmerStops = r.stops.filter((s) => s.type === "farmer");
        if (farmerStops.length < 2) continue;
        const clat = farmerStops.reduce((s, p) => s + p.lat, 0) / farmerStops.length;
        const clng = farmerStops.reduce((s, p) => s + p.lng, 0) / farmerStops.length;
        for (const s of farmerStops) {
          segments.push({ source: [s.lng, s.lat], target: [clng, clat], vehicleId: r.vehicleId });
        }
      }
      return new deck.LineLayer({
        id: "pooling",
        data: segments,
        getSourcePosition: (d) => d.source,
        getTargetPosition: (d) => d.target,
        getColor: (d) => (colored ? [...Vis.colorForId(d.vehicleId), 160] : [130, 130, 120, 110]),
        getWidth: 1.4,
        widthMinPixels: 1,
      });
    }

    _routeLayer(routes, opts) {
      opts = opts || {};
      const id = opts.id || "routes";
      const dashed = !!opts.dashed;
      const opacity = opts.opacity === undefined ? 210 : opts.opacity;
      const widthPx = opts.widthPx || 3;
      const props = {
        id,
        data: routes,
        getPath: (r) => r.coordinates,
        getColor: (r) => [...Vis.colorForId(r.vehicleId), opacity],
        getWidth: widthPx,
        widthUnits: "pixels",
        widthMinPixels: 2,
        widthMaxPixels: 7,
        pickable: true,
        onClick: (info) => info.object && this._emitSelect("route", info.object.id, info.object),
        capRounded: true,
        jointRounded: true,
      };
      if (dashed) {
        props.extensions = [new deck.PathStyleExtension({ dash: true })];
        props.getDashArray = [3, 2];
        props.dashJustified = true;
      }
      return new deck.PathLayer(props);
    }

    _vehicleLayer(positions) {
      const layers = [
        new deck.ScatterplotLayer({
          id: "vehicles",
          data: positions,
          getPosition: (v) => [v.lng, v.lat],
          getRadius: 9,
          radiusUnits: "pixels",
          stroked: true,
          getLineColor: [20, 20, 16, 255],
          lineWidthMinPixels: 2,
          getFillColor: (v) => [...Vis.colorForId(v.vehicleId), 255],
          pickable: true,
          onClick: (info) => info.object && this._emitSelect("vehicle", info.object.vehicleId, info.object),
        }),
      ];
      if (this.mode3d) return layers;
      layers.push(
        new deck.IconLayer({
          id: "vehicle-icons",
          data: positions,
          iconAtlas: this._iconAtlas.atlas,
          iconMapping: this._iconAtlas.mapping,
          getIcon: () => "vehicle",
          getPosition: (v) => [v.lng, v.lat],
          getSize: 13,
          sizeUnits: "pixels",
          getColor: [255, 255, 255, 235],
          pickable: false,
        }),
        new deck.TextLayer({
          id: "vehicle-labels",
          data: positions,
          getPosition: (v) => [v.lng, v.lat],
          getText: (v) => `V${v.vehicleId}`,
          getSize: 10,
          getColor: [255, 255, 255, 255],
          getPixelOffset: [0, -13],
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          fontWeight: 700,
        })
      );
      return layers;
    }

    _vehicleTruckLayer(positions) {
      // A real truck silhouette (cargo box + cab + 4 wheels), oriented
      // along the vehicle's real direction of travel (heading, computed in
      // simulationEngine.js from consecutive waypoints) -- see
      // models3d.js. Not memoized: this runs every animation frame like
      // the flat vehicle layer above, and it's just as cheap (one truck's
      // worth of small polygons per active vehicle).
      const cargos = [], cabs = [], wheels = [];
      for (const v of positions) {
        const fp = Vis.vehicleFootprints(v.lng, v.lat, v.heading);
        cargos.push({ polygon: fp.cargo, elevation: fp.cargoHeight, v });
        cabs.push({ polygon: fp.cab, elevation: fp.cabHeight, v });
        for (const w of fp.wheels) wheels.push({ polygon: w, elevation: fp.wheelHeight, v });
      }
      const tint = (d) => [...Vis.colorForId(d.v.vehicleId), 255];
      return [
        new deck.PolygonLayer({
          id: "vehicle-cargo", data: cargos, getPolygon: (d) => d.polygon, getElevation: (d) => d.elevation,
          extruded: true, wireframe: true, getLineColor: [20, 20, 16, 200], lineWidthMinPixels: 1,
          getFillColor: tint, pickable: true,
          onClick: (info) => info.object && this._emitSelect("vehicle", info.object.v.vehicleId, info.object.v),
        }),
        new deck.PolygonLayer({
          id: "vehicle-cab", data: cabs, getPolygon: (d) => d.polygon, getElevation: (d) => d.elevation,
          extruded: true, wireframe: true, getLineColor: [20, 20, 16, 200], lineWidthMinPixels: 1,
          getFillColor: tint, pickable: true,
          onClick: (info) => info.object && this._emitSelect("vehicle", info.object.v.vehicleId, info.object.v),
        }),
        new deck.PolygonLayer({
          id: "vehicle-wheels", data: wheels, getPolygon: (d) => d.polygon, getElevation: (d) => d.elevation,
          extruded: true, getFillColor: [24, 22, 20, 255], pickable: false,
        }),
        new deck.TextLayer({
          id: "vehicle-labels-3d",
          data: positions,
          getPosition: (v) => [v.lng, v.lat],
          getText: (v) => `V${v.vehicleId}`,
          getSize: 11,
          getColor: [255, 255, 255, 255],
          getPixelOffset: [0, -58],
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          fontWeight: 700,
        }),
      ];
    }

    _spotlightLayer(positions) {
      // A soft glow under each currently-active vehicle: three concentric,
      // decreasingly-opaque discs fake a radial falloff (deck.gl's
      // ScatterplotLayer has no blur), in the vehicle's own color so the
      // "spotlight" reads as pointing at that specific vehicle's story.
      const rings = [
        { radius: 46, alpha: 28 },
        { radius: 28, alpha: 45 },
        { radius: 14, alpha: 70 },
      ];
      return rings.map((ring, i) => new deck.ScatterplotLayer({
        id: `spotlight-${i}`,
        data: positions,
        getPosition: (v) => [v.lng, v.lat],
        getRadius: ring.radius,
        radiusUnits: "pixels",
        stroked: false,
        getFillColor: (v) => [...Vis.colorForId(v.vehicleId), ring.alpha],
      }));
    }

    // ---- main render -------------------------------------------------------

    _render() {
      if (!this.overlay || !this.solution) return;
      const vis = STAGE_VISIBILITY[this.stage] || STAGE_VISIBILITY[5];
      const layers = [];

      // Only farmers/markets depend on the visited sets (their stroke
      // color), so only their cache keys include visitedGeneration --
      // routes/pooling don't change once a solution/stage is loaded, and
      // shouldn't be rebuilt every time a vehicle moves or a farmer gets
      // visited.
      if (vis.farmers) {
        layers.push(...this._memoLayers(
          "farmers", [this.solution, vis.colored, this.visitedGeneration, this.mode3d],
          () => this._farmerLayer(this.solution.farmers, vis.colored, this.visitedFarmerIds)
        ));
        if (this.mode3d) {
          layers.push(...this._memoLayers(
            "farmer-crates", [this.solution, vis.colored],
            () => [this._farmerCrateLayer(this.solution.farmers, vis.colored)]
          ));
        }
      }
      if (vis.pooling) {
        layers.push(...this._memoLayers(
          "pooling", [this.solution, vis.colored],
          () => [this._poolingLayer(this.solution.routes, vis.colored)]
        ));
      }
      if (vis.markets) {
        layers.push(...this._memoLayers(
          "markets", [this.solution, this.visitedGeneration, this.mode3d],
          () => this._marketLayer(this.solution.markets, this.visitedMarketIds)
        ));
        if (this.mode3d) {
          layers.push(...this._memoLayers(
            "market-buildings", [this.solution],
            () => this._marketBuildingLayer(this.solution.markets)
          ));
        }
      }
      if (vis.routes) {
        layers.push(...this._memoLayers(
          "routes", [this.solution, this.compareMode],
          () => [this._routeLayer(this.solution.routes, { id: "routes", opacity: this.compareMode ? 235 : 210 })]
        ));
        if (this.compareMode && this.compareSolution) {
          layers.push(...this._memoLayers(
            "routes-compare", [this.compareSolution],
            () => [this._routeLayer(this.compareSolution.routes, {
              id: "routes-compare", dashed: true, opacity: 150, widthPx: 2.4,
            })]
          ));
        }
      }
      if (vis.vehicles && this.vehiclePositions.length) {
        // Deliberately NOT memoized -- this is the one thing that
        // legitimately changes every animation frame during playback, and
        // it's cheap (one entry per currently-active vehicle, not per
        // farmer), so there's nothing to gain by caching it.
        if (this.theaterMode) layers.push(...this._spotlightLayer(this.vehiclePositions));
        layers.push(...this._vehicleLayer(this.vehiclePositions));
        if (this.mode3d) layers.push(...this._vehicleTruckLayer(this.vehiclePositions));
      }

      this.overlay.setProps({ layers });
    }
  }

  Vis.LogisticsMap = LogisticsMap;
