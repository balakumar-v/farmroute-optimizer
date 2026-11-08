// frontend/vis/simulationEngine.js
// -------------------------------------------------------------------------
// Turns a solution's `simulationEvents` (see visualization_adapter.py) into
// a scrubbable timeline: play/pause/reset/speed/seek, plus a snapshot() of
// "where is every active vehicle right now, what has it picked up/delivered
// so far, which farmers/markets have been visited" for a given simulated
// hour. Never mutates the optimization result -- only reads events/routes
// that were already computed. Deterministic: the same time `t` always
// produces the same snapshot, independent of playback speed or direction.
(function () {
  "use strict";
  const Vis = (window.Vis = window.Vis || {});

  class SimulationEngine {
    /**
     * @param {Array} events  solution.simulationEvents
     * @param {Array} routes  solution.routes (need id, vehicleId, coordinates, farmerIds, marketIds)
     */
    constructor(events, routes) {
      this.events = (events || []).slice().sort((a, b) => a.timestamp - b.timestamp);
      this.routesById = new Map((routes || []).map((r) => [r.id, r]));
      this.eventsByTrip = new Map();
      for (const e of this.events) {
        if (!this.eventsByTrip.has(e.tripId)) this.eventsByTrip.set(e.tripId, []);
        this.eventsByTrip.get(e.tripId).push(e);
      }
      this.eventsByVehicle = new Map();
      for (const e of this.events) {
        if (e.vehicleId === undefined || e.vehicleId === null) continue;
        if (!this.eventsByVehicle.has(e.vehicleId)) this.eventsByVehicle.set(e.vehicleId, []);
        this.eventsByVehicle.get(e.vehicleId).push(e);
      }

      this.minT = this.events.length ? this.events[0].timestamp : 0;
      this.maxT = this.events.length ? this.events[this.events.length - 1].timestamp : 1;
      if (this.maxT <= this.minT) this.maxT = this.minT + 1; // avoid a zero-length timeline

      this.t = this.minT;
      this.playing = false;
      this.speed = 2; // simulated hours per real second
      this._raf = null;
      this._lastFrameTime = null;
      this._listeners = new Set();

      this._waypointsByTrip = this._buildWaypoints();
      this._tripWindowsByVehicle = this._buildTripWindows();

      // Perf note (see snapshot() below): the naive version of this class
      // rescanned every event in the whole timeline, for every vehicle, on
      // every single animation frame -- fine at n=100 farmers, but a real
      // per-frame cost at n=1,000-10,000 (thousands of events x 60fps).
      // These three fields are the incremental cursor that avoids that:
      // _cursorIdx/_cursorT track how far into the sorted `events` array
      // the cumulative visited-farmer/visited-market sets have already
      // been folded in, so a forward-playing timeline (the common case)
      // only processes the NEW events since the last frame, not the whole
      // history again. A backward seek (scrubbing back) is detected via
      // _cursorT and pays a one-time full rescan from t=minT, which is
      // fine since scrubbing is a discrete user action, not a per-frame
      // cost. _visitedGeneration is a cheap integer that bumps only when
      // the cumulative sets actually changed content this call -- see
      // logisticsMap.js's _render(), which uses it (instead of the Set
      // objects themselves, which are copied fresh each call) to decide
      // whether the farmer/market layers need rebuilding at all.
      this._cursorIdx = 0;
      this._cursorT = -Infinity;
      this._visitedFarmerIds = new Set();
      this._visitedMarketIds = new Set();
      this._lastEvent = null;
      this._visitedGeneration = 0;
    }

    // Waypoints: ordered {t, lat, lng} per trip, used to interpolate a
    // moving vehicle's position between real stop events. The "dispatch"
    // event has no coordinate (this project has no depot location -- see
    // visualization_adapter.py's module docstring), so the first waypoint
    // reuses the first real stop's coordinates at the dispatch timestamp:
    // the vehicle is modeled as already positioned at its first stop while
    // DISPATCH_OVERHEAD_HR/ready-hour waiting elapses, exactly mirroring
    // what the optimizer's own timing model assumes (no travel leg is
    // charged before the first stop).
    _buildWaypoints() {
      const out = new Map();
      for (const [tripId, evts] of this.eventsByTrip.entries()) {
        const stopEvents = evts.filter((e) => e.type === "arrive_farmer" || e.type === "arrive_market");
        const dispatchEvt = evts.find((e) => e.type === "dispatch");
        const waypoints = [];
        if (dispatchEvt && stopEvents.length) {
          waypoints.push({ t: dispatchEvt.timestamp, lat: stopEvents[0].lat, lng: stopEvents[0].lng });
        }
        for (const e of stopEvents) waypoints.push({ t: e.timestamp, lat: e.lat, lng: e.lng });
        out.set(tripId, waypoints);
      }
      return out;
    }

    // One-time (constructor-only) precompute of each vehicle's trips as a
    // small, time-sorted array of {tripId, dispatchT, completeT, events}.
    // snapshot() used to rebuild this exact grouping (a fresh Map + a scan
    // of every one of the vehicle's events) from scratch on every frame;
    // now it's built once and reused, and snapshot() only needs a binary
    // search into each vehicle's own (short) trip list instead of a linear
    // scan of every event that vehicle ever generated.
    _buildTripWindows() {
      const out = new Map();
      for (const [vehicleId, evts] of this.eventsByVehicle.entries()) {
        const byTrip = new Map();
        for (const e of evts) {
          if (!byTrip.has(e.tripId)) byTrip.set(e.tripId, []);
          byTrip.get(e.tripId).push(e);
        }
        const windows = [];
        for (const [tripId, tripEvts] of byTrip.entries()) {
          windows.push({
            tripId,
            dispatchT: tripEvts[0].timestamp,
            completeT: tripEvts[tripEvts.length - 1].timestamp,
            events: tripEvts, // already timestamp-ordered (this.events is sorted before grouping)
          });
        }
        windows.sort((a, b) => a.dispatchT - b.dispatchT);
        out.set(vehicleId, windows);
      }
      return out;
    }

    // Index of the last window with dispatchT <= t (binary search over an
    // already-sorted, per-vehicle array), or -1 if none has dispatched yet.
    _findTripWindowIndex(windows, t) {
      let lo = 0, hi = windows.length - 1, ans = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (windows[mid].dispatchT <= t) { ans = mid; lo = mid + 1; }
        else hi = mid - 1;
      }
      return ans;
    }

    // Advances (or, on a backward seek, rebuilds) the cumulative
    // visited-farmer/visited-market state up to time t. See the
    // constructor's comment on _cursorIdx for why this replaces a full
    // rescan of `this.events` on every call.
    _ensureVisitedCursor(t) {
      let changed = false;
      if (t < this._cursorT) {
        this._cursorIdx = 0;
        this._visitedFarmerIds = new Set();
        this._visitedMarketIds = new Set();
        this._lastEvent = null;
        changed = true;
      }
      while (this._cursorIdx < this.events.length && this.events[this._cursorIdx].timestamp <= t) {
        const e = this.events[this._cursorIdx];
        this._lastEvent = e;
        if (e.type === "pickup") { this._visitedFarmerIds.add(e.locationId); changed = true; }
        if (e.type === "delivery") { this._visitedMarketIds.add(e.locationId); changed = true; }
        this._cursorIdx++;
      }
      this._cursorT = t;
      if (changed) this._visitedGeneration++;
    }

    on(fn) { this._listeners.add(fn); return () => this._listeners.delete(fn); }
    _notify() { const snap = this.snapshot(); for (const fn of this._listeners) fn(snap); }

    play() {
      if (this.playing) return;
      if (this.t >= this.maxT) this.t = this.minT; // replay from the start if already finished
      this.playing = true;
      this._lastFrameTime = performance.now();
      this._tick();
    }
    pause() { this.playing = false; if (this._raf) cancelAnimationFrame(this._raf); this._raf = null; }
    reset() { this.pause(); this.t = this.minT; this._notify(); }
    setSpeed(hoursPerSecond) { this.speed = hoursPerSecond; }
    seek(t) { this.t = Math.min(this.maxT, Math.max(this.minT, t)); this._notify(); }
    get progress() { return (this.t - this.minT) / (this.maxT - this.minT); }
    seekProgress(p) { this.seek(this.minT + p * (this.maxT - this.minT)); }

    _tick() {
      if (!this.playing) return;
      const now = performance.now();
      const dtSeconds = (now - this._lastFrameTime) / 1000;
      this._lastFrameTime = now;
      this.t += dtSeconds * this.speed;
      if (this.t >= this.maxT) {
        this.t = this.maxT;
        this.playing = false;
        this._notify();
        return;
      }
      this._notify();
      this._raf = requestAnimationFrame(() => this._tick());
    }

    // Compass bearing (degrees, 0 = north, clockwise) from a to b. Used only
    // to orient the 3D truck model along its direction of travel.
    static _bearing(a, b) {
      const toRad = Math.PI / 180;
      const dLng = (b.lng - a.lng) * toRad;
      const lat1 = a.lat * toRad, lat2 = b.lat * toRad;
      const y = Math.sin(dLng) * Math.cos(lat2);
      const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
      return (Math.atan2(y, x) / toRad + 360) % 360;
    }

    // Heading for waypoint index i: the direction of the first non-zero-length
    // segment at/after i (a parked vehicle faces where it is about to go),
    // else the last non-zero-length segment before it.
    _headingAt(wps, i) {
      const distinct = (p, q) => p.lat !== q.lat || p.lng !== q.lng;
      for (let k = i; k < wps.length - 1; k++) {
        if (distinct(wps[k], wps[k + 1])) return SimulationEngine._bearing(wps[k], wps[k + 1]);
      }
      for (let k = Math.min(i, wps.length - 1); k > 0; k--) {
        if (distinct(wps[k - 1], wps[k])) return SimulationEngine._bearing(wps[k - 1], wps[k]);
      }
      return 0;
    }

    /** Public: {lat,lng,heading} of one trip's vehicle at time t (or null). Lets the
     * theater follow a single "protagonist" truck without going through the
     * all-vehicles snapshot(). */
    positionOfTrip(tripId, t) { return this._positionAt(tripId, t === undefined ? this.t : t); }

    _positionAt(tripId, t) {
      const wps = this._waypointsByTrip.get(tripId);
      if (!wps || !wps.length) return null;
      if (t <= wps[0].t) return { lat: wps[0].lat, lng: wps[0].lng, heading: this._headingAt(wps, 0) };
      for (let i = 0; i < wps.length - 1; i++) {
        const a = wps[i], b = wps[i + 1];
        if (t >= a.t && t <= b.t) {
          const frac = b.t === a.t ? 0 : (t - a.t) / (b.t - a.t);
          return { lat: a.lat + (b.lat - a.lat) * frac, lng: a.lng + (b.lng - a.lng) * frac, heading: this._headingAt(wps, i) };
        }
      }
      const last = wps[wps.length - 1];
      return { lat: last.lat, lng: last.lng, heading: this._headingAt(wps, wps.length - 1) };
    }

    /** Everything the map/details panel needs to render "right now": active
     * vehicle positions+loads, which trips are in progress/complete, which
     * farmers/markets have been visited, and the most recent event (for a
     * status line). All derived from real events -- loadKg comes from
     * each pickup/delivery's real loadChangeKg, nothing invented.
     *
     * Same output shape and semantics as before -- see the constructor's
     * comment on _cursorIdx and _buildTripWindows() for what changed
     * underneath: this used to be two full scans of every event in the
     * timeline (one for visited-sets, one per vehicle for position/load),
     * repeated on every animation frame regardless of how much time
     * actually advanced. It's now an incremental cursor (visited-sets) plus
     * a binary search into each vehicle's own short trip list (position),
     * so per-frame cost during forward playback scales with what changed
     * since the last frame, not with total farmer/event count. */
    snapshot() {
      const t = this.t;
      this._ensureVisitedCursor(t);

      const vehiclePositions = [];
      const activeTripIds = new Set();
      const completeTripIds = new Set();

      for (const [vehicleId, windows] of this._tripWindowsByVehicle.entries()) {
        const idx = this._findTripWindowIndex(windows, t);
        // Trips for one vehicle never overlap (see visualization_adapter.py),
        // and windows are sorted by dispatchT, so every window before idx
        // must already have completed by the time windows[idx] dispatched.
        for (let i = 0; i < idx; i++) completeTripIds.add(windows[i].tripId);
        if (idx < 0) continue;
        const w = windows[idx];
        if (t > w.completeT) { completeTripIds.add(w.tripId); continue; }
        activeTripIds.add(w.tripId);
        const pos = this._positionAt(w.tripId, t);
        if (!pos) continue;
        let loadKg = 0;
        for (const e of w.events) {
          if (e.timestamp > t) break;
          if (typeof e.loadChangeKg === "number") loadKg += e.loadChangeKg;
        }
        const route = this.routesById.get(w.tripId);
        vehiclePositions.push({
          vehicleId, tripId: w.tripId, lat: pos.lat, lng: pos.lng, heading: pos.heading,
          loadKg: Math.max(0, loadKg),
          capacityKg: route ? route.totalQtyKg : undefined,
        });
      }

      return {
        t, minT: this.minT, maxT: this.maxT, playing: this.playing,
        vehiclePositions, activeTripIds, completeTripIds,
        // Copies, not the live internal Sets -- cheap (bounded by farmer/
        // market count, not event count) and keeps callers from being able
        // to mutate this engine's own cumulative state.
        visitedFarmerIds: new Set(this._visitedFarmerIds),
        visitedMarketIds: new Set(this._visitedMarketIds),
        lastEvent: this._lastEvent,
        // Bumps only when the visited sets actually changed content this
        // call -- see logisticsMap.js's _render(), which uses this integer
        // (not the Set objects, which are fresh copies every call and so
        // useless as a cache key) to decide whether the farmer/market
        // layers need rebuilding at all.
        visitedGeneration: this._visitedGeneration,
      };
    }
  }

  Vis.SimulationEngine = SimulationEngine;
})();
