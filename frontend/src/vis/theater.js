// frontend/vis/theater.js
// -------------------------------------------------------------------------
// Fullscreen "theater" presentation for a computed plan: a slideshow, not a
// continuously-ticking animation -- each click of Next/Back moves exactly
// one real step of Vis.buildNarrative()'s story, the camera flies to
// whatever that step is about, and the same sentence appears as a
// subtitle-style caption. Two synthetic bookend steps (title/summary) open
// and close the show with real solution.summary figures, never invented
// ones.
//
// The story is told one truck at a time: each dispatched vehicle is the
// "protagonist" of its own chapter (pool -> depart -> pickups -> sale ->
// trip complete) and the show follows exactly that truck until its trip is
// done, then hands over to the next truck. Only the protagonist is drawn,
// and on Next it actually DRIVES from its previous stop to the next one
// (engine.positionOfTrip sampled every animation frame) while the camera
// follows -- the caption appears once it arrives. Farmers/markets served in
// earlier chapters stay highlighted as visited, so the map accumulates the
// story as it goes.
//
// While open, this file owns the map's vehicle/visited state and does NOT
// drive engine playback; on close the main tab's engine state is restored
// by the onClose callback.
import { Vis } from "./namespace.js";

  function fmt(n, digits) {
    if (n === undefined || n === null || Number.isNaN(n)) return "\u2013";
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 0 : digits });
  }
  function inr(n, digits) { return `\u20B9${fmt(n, digits)}`; }

  // ---- synthetic bookend steps, built from real solution.summary fields --

  function titleStep(solution, nTrucks) {
    const summary = solution.summary || {};
    const vehiclesUsed = summary.vehicles_used !== undefined
      ? summary.vehicles_used : solution.vehicles.filter((v) => v.used).length;
    const nF = solution.farmers.length, nM = solution.markets.length;
    return {
      kind: "title", t: null, subjects: [],
      caption: `Today's plan: ${nF} farmer${nF === 1 ? "" : "s"}, ${vehiclesUsed} vehicle${vehiclesUsed === 1 ? "" : "s"} on the road, ` +
        `${nM} market${nM === 1 ? "" : "s"} ready to buy. We'll follow the trucks one at a time.`,
    };
  }

  function summaryStep(solution) {
    const summary = solution.summary || {};
    const vehiclesUsed = summary.vehicles_used;
    return {
      kind: "summary", t: null, subjects: [],
      caption: `By day's end: ${fmt(summary.pct_qty_served, 1)}% of the harvest sold, ` +
        `${inr(summary.net_return)} net return, ${vehiclesUsed !== undefined ? vehiclesUsed : "\u2013"} vehicle(s) on the road.`,
    };
  }

  const HOURS_TO_MS_EASE = (k) => (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2);

  function haversineKm(a, b) {
    const R = 6371, toRad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * toRad, dLng = (b.lng - a.lng) * toRad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * toRad) * Math.cos(b.lat * toRad) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  // zoom that keeps a leg of the given length comfortably on screen
  function zoomForLegKm(km) {
    if (km < 0.25) return 16;
    if (km < 1) return 15.3;
    if (km < 2.5) return 14.6;
    if (km < 6) return 13.8;
    return 13;
  }

  class TheaterMode {
    /**
     * @param {Object} opts
     * @param {HTMLElement} opts.overlayEl - fullscreen overlay root (hidden by default)
     * @param {HTMLElement} opts.mapSlotEl - slot inside the theater box the live map container is moved into
     * @param {Object} opts.map - the shared Vis.LogisticsMap instance
     * @param {() => Object} opts.getSolution
     * @param {() => Object} opts.getEngine
     * @param {() => void} [opts.onClose]
     * @param {(on:boolean) => void} [opts.on3DChange] - called when the theater flips 3D so the main tab's button can follow
     * @param {Object} opts.els - { caption, prevBtn, nextBtn, exitBtn, freeLookBtn, view3dBtn, chaseBtn, progressText, progressFill, followLabel }
     */
    constructor(opts) {
      this.overlayEl = opts.overlayEl;
      this.mapSlotEl = opts.mapSlotEl;
      this.map = opts.map;
      this.legendEl = opts.legendEl || null;
      this.getSolution = opts.getSolution;
      this.getEngine = opts.getEngine;
      this.onClose = opts.onClose || (() => {});
      this.on3DChange = opts.on3DChange || (() => {});
      this.els = opts.els;

      this.isOpen = false;
      this.freeLook = false;
      this.chase = false;
      this.steps = [];
      this.index = 0;

      this._tween = null;
      this._tripId = null; // trip whose truck is currently drawn
      this._t = 0; // sim time that truck is currently drawn at
      this._genCounter = 0;
      this._lastVisKey = "";

      this._realMapEl = null;
      this._originalParent = null;
      this._originalNextSibling = null;

      this._onKeydown = this._onKeydown.bind(this);
      this.els.prevBtn.addEventListener("click", () => this.prev());
      this.els.nextBtn.addEventListener("click", () => this.next());
      this.els.exitBtn.addEventListener("click", () => this.close());
      this.els.freeLookBtn.addEventListener("click", () => this.toggleFreeLook());
      if (this.els.view3dBtn) this.els.view3dBtn.addEventListener("click", () => this.toggle3D());
      if (this.els.chaseBtn) this.els.chaseBtn.addEventListener("click", () => this.toggleChase());
    }

    // ---- story assembly: title, one chapter per truck, unserved, summary --
    _buildSteps(solution) {
      const narrative = Vis.buildNarrative(solution);
      const byTrip = new Map();
      const loose = [];
      for (const s of narrative) {
        if (s.tripId) {
          if (!byTrip.has(s.tripId)) byTrip.set(s.tripId, []);
          byTrip.get(s.tripId).push(s);
        } else loose.push(s);
      }
      const trips = Array.from(byTrip.entries())
        .map(([tripId, list]) => ({ tripId, list: list.sort((a, b) => a.t - b.t) }))
        .sort((a, b) => a.list[0].t - b.list[0].t);
      this._chapterTripIds = trips.map((c) => c.tripId);

      const steps = [titleStep(solution, trips.length)];
      trips.forEach((c, k) => {
        c.list.forEach((s, j) => {
          const step = Object.assign({}, s, { chapter: k });
          if (j === 0 && s.kind === "pool") {
            const lead = k === 0 ? `Meet Vehicle ${s.vehicleId}, our first truck to follow. `
              : `Now let's follow Vehicle ${s.vehicleId}. `;
            step.caption = lead + s.caption;
          }
          steps.push(step);
        });
      });
      loose.forEach((s) => steps.push(Object.assign({}, s, { chapter: null })));
      steps.push(summaryStep(solution));
      return steps;
    }

    _indexEvents(solution) {
      this._eventsByTrip = new Map();
      for (const e of solution.simulationEvents || []) {
        if (!this._eventsByTrip.has(e.tripId)) this._eventsByTrip.set(e.tripId, []);
        this._eventsByTrip.get(e.tripId).push(e);
      }
      for (const list of this._eventsByTrip.values()) list.sort((a, b) => a.timestamp - b.timestamp);
    }

    /** Farmers/markets served by all trips in chapters strictly before `chapterIdx`
     * (or all chapters when chapterIdx is Infinity). */
    _baseVisited(chapterIdx) {
      const f = new Set(), m = new Set();
      this._chapterTripIds.forEach((tripId, k) => {
        if (k >= chapterIdx) return;
        for (const e of this._eventsByTrip.get(tripId) || []) {
          if (e.type === "pickup") f.add(e.locationId);
          else if (e.type === "delivery") m.add(e.locationId);
        }
      });
      return { f, m };
    }

    /** Draws the protagonist at time t and sets visited highlighting. */
    _drawState(step, t, forceVisitedRefresh) {
      const engine = this.getEngine();
      const chapter = step.chapter;
      let positions = [];
      const base = this._baseVisited(chapter === null || chapter === undefined ? Infinity : chapter);
      if (step.tripId && chapter !== null && chapter !== undefined) {
        const pos = engine.positionOfTrip(step.tripId, t);
        if (pos) positions = [{ vehicleId: step.vehicleId, tripId: step.tripId, lat: pos.lat, lng: pos.lng, heading: pos.heading }];
        for (const e of this._eventsByTrip.get(step.tripId) || []) {
          if (e.timestamp > t) break;
          if (e.type === "pickup") base.f.add(e.locationId);
          else if (e.type === "delivery") base.m.add(e.locationId);
        }
      }
      if (step.kind === "summary") { const all = this._baseVisited(Infinity); base.f = all.f; base.m = all.m; }
      if (step.kind === "title") { base.f = new Set(); base.m = new Set(); }
      this.map.setVehiclePositions(positions);
      const key = `${step.chapter}|${base.f.size}|${base.m.size}`;
      if (forceVisitedRefresh || key !== this._lastVisKey) {
        this._lastVisKey = key;
        this.map.setVisitedSets(base.f, base.m, 1000000 + this._genCounter++);
      }
      this._tripId = step.tripId || null;
      this._t = t;
    }

    _stepTime(step) {
      if (step.kind === "title") return this.getEngine().minT;
      if (step.kind === "summary") return this.getEngine().maxT;
      return step.t;
    }

    // ---- open / close ----------------------------------------------------
    /** @param {HTMLElement} realMapContainerEl - the live #mapContainer node to reparent in. Returns false (no-op) if there's no plan loaded yet. */
    open(realMapContainerEl) {
      const solution = this.getSolution();
      const engine = this.getEngine();
      if (!solution || !engine) return false;

      engine.pause();
      this._indexEvents(solution);
      this.steps = this._buildSteps(solution);
      this.index = 0;
      this.freeLook = false;
      this.chase = false;
      this._tripId = null;
      this._lastVisKey = "";

      this._realMapEl = realMapContainerEl;
      this._originalParent = this._realMapEl.parentElement;
      this._originalNextSibling = this._realMapEl.nextSibling;
      this.mapSlotEl.appendChild(this._realMapEl);
      this.map.resize();
      if (this.legendEl) this.legendEl.hidden = true;

      this.map.setTheaterMode(true);
      this.map.setInteractive(false);
      this._syncChips();

      this.isOpen = true;
      this.overlayEl.hidden = false;
      document.body.style.overflow = "hidden";
      window.addEventListener("keydown", this._onKeydown);

      this._show(0, false);
      return true;
    }

    close() {
      if (!this.isOpen) return;
      this._cancelTween();
      this.chase = false;
      this.isOpen = false;
      window.removeEventListener("keydown", this._onKeydown);
      document.body.style.overflow = "";
      this.overlayEl.hidden = true;

      this.map.setFollow(null, { restore: false });
      this.map.setInteractive(true);
      this.map.setTheaterMode(false);
      if (this._originalParent) {
        this._originalParent.insertBefore(this._realMapEl, this._originalNextSibling);
      }
      this.map.resize();
      this.map.fitToData();
      if (this.legendEl) this.legendEl.hidden = false;

      this.onClose(); // main tab re-syncs vehicle/visited state from its own engine
    }

    // ---- toggles -----------------------------------------------------------
    toggleFreeLook() {
      this.freeLook = !this.freeLook;
      this.map.setInteractive(this.freeLook);
      this._syncChips();
    }

    toggle3D() {
      const on = !this.map.mode3d;
      this.map.set3D(on);
      if (!on) this.chase = false;
      this.on3DChange(on);
      this._syncChips();
      this._applyCameraForCurrentStep();
    }

    toggleChase() {
      this.chase = !this.chase;
      if (this.chase && !this.map.mode3d) { this.map.set3D(true); this.on3DChange(true); }
      this._syncChips();
      this._applyCameraForCurrentStep();
    }

    _syncChips() {
      const set = (btn, on, label) => { if (!btn) return; btn.textContent = `${label}: ${on ? "On" : "Off"}`; btn.classList.toggle("theater-chip--on", on); };
      set(this.els.freeLookBtn, this.freeLook, "Free look");
      set(this.els.view3dBtn, !!this.map.mode3d, "3D");
      set(this.els.chaseBtn, this.chase, "Chase cam");
    }

    _onKeydown(e) {
      if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); this.next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); this.prev(); }
      else if (e.key === "Escape") this.close();
    }

    // ---- navigation --------------------------------------------------------
    prev() {
      if (this.index === 0) return;
      this._cancelTween();
      this._show(this.index - 1, false);
    }

    next() {
      if (this._tween) { this._finishTween(); return; } // click while driving = skip to arrival
      if (this.index < this.steps.length - 1) this._show(this.index + 1, true);
      else this.close();
    }

    // ---- showing one step --------------------------------------------------
    _show(index, animate) {
      const fromStep = this.steps[this.index];
      const prevTripId = this._tripId, prevT = this._t;
      this.index = index;
      const step = this.steps[index];
      const toT = this._stepTime(step);

      this._updateChrome(step);

      const sameChapter = animate && step.tripId && step.tripId === prevTripId && step.chapter === fromStep.chapter;
      const legPts = sameChapter ? this._legEndpoints(step, prevT, toT) : null;
      const legKm = legPts ? haversineKm(legPts[0], legPts[1]) : 0;
      const moving = legKm > 0.005;

      if (!moving) {
        // discrete jump (chapter change, Back, static step): place everything now
        this._drawState(step, toT, true);
        this._setCaption(step.caption, true);
        this._cameraFor(step, null);
        return;
      }

      // truck drives from where it was to where this step happens
      this._setCaption("", false);
      this._cameraFor(step, legKm);
      const dur = Math.min(3200, Math.max(900, 900 + legKm * 450));
      const start = performance.now();
      const tween = { step, fromT: prevT, toT, start, dur, raf: null };
      this._tween = tween;
      const frame = (now) => {
        if (this._tween !== tween) return;
        const k = Math.min(1, (now - start) / dur);
        this._drawState(step, tween.fromT + (tween.toT - tween.fromT) * HOURS_TO_MS_EASE(k), false);
        if (k < 1) tween.raf = requestAnimationFrame(frame);
        else this._finishTween();
      };
      tween.raf = requestAnimationFrame(frame);
    }

    _legEndpoints(step, fromT, toT) {
      const engine = this.getEngine();
      const a = engine.positionOfTrip(step.tripId, fromT), b = engine.positionOfTrip(step.tripId, toT);
      return a && b ? [a, b] : null;
    }

    _cancelTween() {
      if (!this._tween) return;
      if (this._tween.raf) cancelAnimationFrame(this._tween.raf);
      this._tween = null;
    }

    /** Snap a running drive to its arrival state and reveal the caption. */
    _finishTween() {
      const tw = this._tween;
      if (!tw) return;
      if (tw.raf) cancelAnimationFrame(tw.raf);
      this._tween = null;
      this._drawState(tw.step, tw.toT, true);
      this._setCaption(tw.step.caption, true);
      if (!this.chase && tw.step.subjects && tw.step.subjects.length === 1 && !this.map.follow) {
        this.map.flyToPoints(tw.step.subjects, { duration: 500 });
      } else if (!this.chase && tw.step.subjects && tw.step.subjects.length === 1) {
        this.map.setFollow(null, { restore: false });
        this.map.flyToPoints(tw.step.subjects, { duration: 500 });
      }
    }

    // ---- camera ------------------------------------------------------------
    _cameraFor(step, legKm) {
      if (step.kind === "title" || step.kind === "summary" || step.chapter === null || step.chapter === undefined) {
        this.map.setFollow(null, { restore: false });
        this.map.flyToPoints(step.subjects, {});
        return;
      }
      if (this.chase) {
        this.map.setFollow({ mode: "chase", vehicleId: step.vehicleId, zoom: 17.1 });
        return;
      }
      if (legKm !== null && legKm !== undefined && legKm > 0.005) {
        this.map.setFollow({ mode: "top", vehicleId: step.vehicleId, zoom: zoomForLegKm(legKm) });
        return;
      }
      this.map.setFollow(null, { restore: false });
      this.map.flyToPoints(step.subjects, {});
    }

    _applyCameraForCurrentStep() {
      const step = this.steps[this.index];
      if (!step) return;
      const tw = this._tween;
      this._cameraFor(step, tw ? 1 : null);
    }

    // ---- chrome (caption, progress, buttons) -------------------------------
    _setCaption(text, visible) {
      const c = this.els.caption;
      c.textContent = text || "\u00A0";
      c.classList.toggle("theater-caption--hidden", !visible);
    }

    _updateChrome(step) {
      const n = this.steps.length;
      this.els.progressText.textContent = `Step ${this.index + 1} of ${n}`;
      this.els.progressFill.style.width = `${Math.round((100 * (this.index + 1)) / n)}%`;
      this.els.prevBtn.disabled = this.index === 0;
      this.els.nextBtn.innerHTML = this.index === n - 1
        ? 'Finish<svg class="i"><use href="#i-check"/></svg>'
        : 'Next<svg class="i"><use href="#i-next"/></svg>';
      if (this.els.followLabel) {
        if (step.chapter !== null && step.chapter !== undefined && step.vehicleId !== null && step.vehicleId !== undefined) {
          this.els.followLabel.hidden = false;
          this.els.followLabel.innerHTML =
            `<span class="follow-dot" style="background:${Vis.colorForIdCss(step.vehicleId)}"></span>` +
            `Following Vehicle ${step.vehicleId} \u00B7 truck ${step.chapter + 1} of ${this._chapterTripIds.length}`;
        } else this.els.followLabel.hidden = true;
      }
    }
  }

  Vis.TheaterMode = TheaterMode;
