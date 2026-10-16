// frontend/vis/narrator.js
// -------------------------------------------------------------------------
// Turns a solution's real routes + simulationEvents into a single,
// chronologically-ordered list of plain-English steps -- "Farmers F3, F5
// pool onto Vehicle 2", "Vehicle 2 picks up 280 kg from Farmer 3", "Vehicle
// 2 sells 780 kg at Market 1 for RS17,160", "Trip complete: net profit
// RS12,400" -- instead of leaving the viewer to reconstruct that story
// themselves from raw dots moving on a map.
//
// Same honesty rules as visualization_adapter.py / panels.js: every number
// shown here is a real field already on the solution (route.revenue,
// event.loadChangeKg, route.marketAllocations, ...), never invented or
// estimated client-side. Where an exact per-market split isn't available
// for an algorithm (see visualization_adapter.py's module docstring), the
// step says so explicitly instead of guessing -- same "exact" vs.
// "aggregate only" distinction panels.js already uses.
import { Vis } from "./namespace.js";

  function fmt(n, digits) {
    if (n === undefined || n === null || Number.isNaN(n)) return "\u2013";
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 0 : digits });
  }
  function inr(n, digits) { return `\u20B9${fmt(n, digits)}`; }
  function kg(n, digits) { return `${fmt(n, digits === undefined ? 1 : digits)} kg`; }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function badge(text) { return `<span class="badge">${esc(text)}</span>`; }

  // ---- one step per real thing that happens -----------------------------
  // Each step carries THREE parallel views of the same real data:
  //   html     - compact, badge-tagged line for the side-panel story list
  //   caption  - a flowing, narrated sentence for the theater/subtitle view
  //   subjects - [{lat,lng}] real coordinates the theater camera should
  //              frame for this step (see theater.js's flyToPoints)
  // Never three different facts -- always the same numbers, phrased twice.

  function poolStep(route, farmersById, vehiclesById) {
    const vehicle = vehiclesById.get(route.vehicleId);
    const farmerTxt = route.farmerIds.map((fid) => `F${fid}`).join(", ");
    const cropTotals = new Map(); // crop -> kg, purely a sum of real loadKg values
    const subjects = [];
    for (const fid of route.farmerIds) {
      const f = farmersById.get(fid);
      if (!f) continue;
      cropTotals.set(f.crop, (cropTotals.get(f.crop) || 0) + f.loadKg);
      subjects.push({ lat: f.lat, lng: f.lng });
    }
    const cropTxt = Array.from(cropTotals.entries()).map(([c, q]) => `${esc(c)} ${kg(q)}`).join(", ");
    const cropTxtPlain = Array.from(cropTotals.entries()).map(([c, q]) => `${c} ${kg(q)}`).join(", ");
    const vehicleTxt = vehicle ? `${esc(vehicle.typeName)}, ${kg(vehicle.capacityKg)} capacity` : "vehicle";
    const typeNamePlain = vehicle ? String(vehicle.typeName).replace(/_/g, " ") : "vehicle";
    const dispatchT = route.__dispatchT !== undefined ? route.__dispatchT : 0;
    const solo = route.farmerIds.length === 1;
    // "pool" implies more than one farmer sharing a trip -- a single-farmer
    // trip (e.g. every Individual Transport route, by that algorithm's own
    // design) gets an honestly different verb instead of overstating it.
    const verb = solo ? `is assigned to` : `pool onto`;
    const soloFarmer = solo ? farmersById.get(route.farmerIds[0]) : null;
    const caption = solo
      ? `Farmer F${route.farmerIds[0]}'s ${kg(route.totalQtyKg)} of ${soloFarmer ? soloFarmer.crop : "produce"} is ready. ` +
        `Vehicle ${route.vehicleId} \u2014 a ${typeNamePlain} \u2014 is sent to collect it.`
      : `Vehicle ${route.vehicleId} \u2014 a ${typeNamePlain} \u2014 is dispatched to gather ${kg(route.totalQtyKg)} from Farmers ${farmerTxt}: ${cropTxtPlain}.`;
    return {
      t: dispatchT - 0.001, // sorts just before this trip's own dispatch event
      vehicleId: route.vehicleId, tripId: route.id, kind: "pool", subjects,
      caption,
      html: `${badge(solo ? "ASSIGN" : "POOL")} Farmer${solo ? "" : "s"} ${esc(farmerTxt)} ${verb} ` +
        `<strong>Vehicle ${route.vehicleId}</strong> (${vehicleTxt}) &mdash; ${kg(route.totalQtyKg)} total (${cropTxt}).`,
    };
  }

  function dispatchStep(evt, route) {
    const firstPt = route.coordinates && route.coordinates[0];
    return {
      t: evt.timestamp, vehicleId: evt.vehicleId, tripId: evt.tripId, kind: "dispatch",
      subjects: firstPt ? [{ lat: firstPt[1], lng: firstPt[0] }] : [],
      caption: `Vehicle ${evt.vehicleId} pulls out and hits the road.`,
      html: `${badge("DEPART")} Vehicle ${evt.vehicleId} sets off to begin pickup.`,
    };
  }

  function pickupStep(pickupEvt, farmersById) {
    const f = farmersById.get(pickupEvt.locationId);
    const cropTxt = f ? ` of ${esc(f.crop)}` : "";
    const cropPlain = f ? ` of ${f.crop}` : "";
    return {
      t: pickupEvt.timestamp, vehicleId: pickupEvt.vehicleId, tripId: pickupEvt.tripId, kind: "pickup",
      subjects: f ? [{ lat: f.lat, lng: f.lng }] : [],
      caption: `Vehicle ${pickupEvt.vehicleId} pulls up to Farmer ${pickupEvt.locationId} and loads ${kg(pickupEvt.loadChangeKg)}${cropPlain}.`,
      html: `${badge("PICKUP")} Vehicle ${pickupEvt.vehicleId} reaches Farmer ${pickupEvt.locationId} and picks up ` +
        `${kg(pickupEvt.loadChangeKg)}${cropTxt}.`,
    };
  }

  function saleStep(deliveryEvt, route, marketsById) {
    const marketId = deliveryEvt.locationId;
    const m = marketsById.get(marketId);
    const allocs = (route.marketAllocations || []).filter((a) => a.market_id === marketId);
    let body, caption;
    if (allocs.length) {
      const parts = allocs.map((a) => {
        const priceTxt = a.price !== null && a.price !== undefined ? ` @ ${inr(a.price, 2)}/kg` : "";
        const lineTotal = a.price !== null && a.price !== undefined ? ` = ${inr(a.kg * a.price, 0)}` : "";
        return `${esc(a.crop)} ${kg(a.kg)}${priceTxt}${lineTotal}`;
      });
      body = `sells ${parts.join("; ")} <span class="data-tag live">exact</span>`;
      if (allocs.length === 1 && allocs[0].price !== null && allocs[0].price !== undefined) {
        caption = `At Market ${marketId}, the ${allocs[0].crop} finds a buyer \u2014 ${kg(allocs[0].kg)} at ${inr(allocs[0].price, 2)}/kg, ${inr(allocs[0].kg * allocs[0].price, 0)} in hand.`;
      } else {
        const plainParts = allocs.map((a) => `${a.crop} ${kg(a.kg)}${a.price !== null && a.price !== undefined ? ` @ ${inr(a.price, 2)}/kg` : ""}`);
        const total = allocs.reduce((s, a) => s + (a.price !== null && a.price !== undefined ? a.kg * a.price : 0), 0);
        caption = `Market ${marketId} takes it all: ${plainParts.join(", ")} \u2014 ${inr(total, 0)} combined.`;
      }
    } else if (deliveryEvt.loadChangeKg !== undefined) {
      body = `delivers ${kg(-deliveryEvt.loadChangeKg)} <span class="data-tag estimated">trip total, not itemized</span>`;
      caption = `Vehicle ${deliveryEvt.vehicleId} unloads ${kg(-deliveryEvt.loadChangeKg)} at Market ${marketId} (trip total only \u2014 this baseline doesn't record the per-crop split).`;
    } else {
      body = `delivers its load <span class="data-tag estimated">trip total, not itemized</span>`;
      caption = `Vehicle ${deliveryEvt.vehicleId} unloads at Market ${marketId} (trip total only \u2014 this baseline doesn't record the per-crop split).`;
    }
    return {
      t: deliveryEvt.timestamp, vehicleId: deliveryEvt.vehicleId, tripId: deliveryEvt.tripId, kind: "sale",
      subjects: m ? [{ lat: m.lat, lng: m.lng }] : [],
      caption,
      html: `${badge("SOLD")} Vehicle ${deliveryEvt.vehicleId} reaches Market ${marketId} and ${body}.`,
    };
  }

  function completeStep(evt, route) {
    const extras = [];
    const extrasCaption = [];
    if (route.spoilageLossKg > 0) { extras.push(`spoilage ${kg(route.spoilageLossKg)}`); extrasCaption.push(`${kg(route.spoilageLossKg)} was lost to spoilage along the way.`); }
    if (route.unsoldKg > 0) { extras.push(`unsold ${kg(route.unsoldKg)}`); extrasCaption.push(`${kg(route.unsoldKg)} went unsold.`); }
    const extraTxt = extras.length ? ` (${extras.join(", ")})` : "";
    const subjects = (route.coordinates || []).map(([lng, lat]) => ({ lat, lng }));
    return {
      t: evt.timestamp, vehicleId: evt.vehicleId, tripId: evt.tripId, kind: "complete", subjects,
      caption: `Trip ${route.id} wraps up: ${inr(route.revenue)} earned, ${inr(route.transportCost)} spent on the road \u2014 ` +
        `${inr(route.netReturn)} net.${extrasCaption.length ? " " + extrasCaption.join(" ") : ""}`,
      html: `${badge("DONE")} Trip ${esc(route.id)} complete &mdash; revenue ${inr(route.revenue)}, ` +
        `transport cost ${inr(route.transportCost)}, <strong>net profit ${inr(route.netReturn)}</strong>${extraTxt}.`,
    };
  }

  function unservedStep(farmerIds, farmersById, atT) {
    const txt = farmerIds.map((fid) => `F${fid}`).join(", ");
    const multi = farmerIds.length > 1;
    const subjects = farmerIds.map((fid) => farmersById.get(fid)).filter(Boolean).map((f) => ({ lat: f.lat, lng: f.lng }));
    return {
      t: atT, vehicleId: null, tripId: null, kind: "unserved", subjects,
      caption: `Not every story has a happy ending \u2014 Farmer${multi ? "s" : ""} ${txt} ${multi ? "were" : "was"} never picked up; ` +
        `no vehicle could reach ${multi ? "them" : "it"} in time.`,
      html: `${badge("UNSERVED")} Farmer${farmerIds.length > 1 ? "s" : ""} ${esc(txt)} ${farmerIds.length > 1 ? "were" : "was"} ` +
        `never picked up &mdash; no vehicle in the fleet reached ${farmerIds.length > 1 ? "them" : "it"} within its pickup window under this plan.`,
    };
  }

  /** Builds the full chronological story for one VisualizationSolution.
   * Returns [] if there's nothing dispatched to narrate. */
  Vis.buildNarrative = function (solution) {
    if (!solution) return [];
    const farmersById = new Map(solution.farmers.map((f) => [f.id, f]));
    const vehiclesById = new Map(solution.vehicles.map((v) => [v.id, v]));
    const marketsById = new Map(solution.markets.map((m) => [m.id, m]));

    const eventsByTrip = new Map();
    for (const e of solution.simulationEvents || []) {
      if (!eventsByTrip.has(e.tripId)) eventsByTrip.set(e.tripId, []);
      eventsByTrip.get(e.tripId).push(e);
    }

    const steps = [];
    for (const route of solution.routes) {
      const evts = (eventsByTrip.get(route.id) || []).slice().sort((a, b) => a.timestamp - b.timestamp);
      const dispatchEvt = evts.find((e) => e.type === "dispatch");
      route.__dispatchT = dispatchEvt ? dispatchEvt.timestamp : 0;
      steps.push(poolStep(route, farmersById, vehiclesById));
      for (let i = 0; i < evts.length; i++) {
        const e = evts[i];
        if (e.type === "dispatch") steps.push(dispatchStep(e, route));
        else if (e.type === "pickup") steps.push(pickupStep(e, farmersById));
        else if (e.type === "delivery") steps.push(saleStep(e, route, marketsById));
        else if (e.type === "complete") steps.push(completeStep(e, route));
        // arrive_farmer / arrive_market carry no new info beyond the
        // pickup/delivery event at the same timestamp -- folded in above.
      }
    }
    if (solution.unservedFarmerIds && solution.unservedFarmerIds.length) {
      const minT = steps.length ? Math.min(...steps.map((s) => s.t)) : 0;
      steps.push(unservedStep(solution.unservedFarmerIds, farmersById, minT));
    }

    steps.sort((a, b) => a.t - b.t);
    steps.forEach((s, i) => { s.key = `${s.kind}-${s.tripId || "x"}-${i}`; });
    return steps;
  };

  // ---- rendering + time-synced highlighting ------------------------------

  function findIndexAtTime(steps, t) {
    // Last index with step.t <= t, via binary search (steps sorted by t).
    let lo = 0, hi = steps.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (steps[mid].t <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  }

  /** Renders a step list into `container` once, then lets callers scrub
   * time cheaply: applyTime(t) only touches the DOM elements that crossed
   * between the previous call and this one (like SimulationEngine's own
   * event cursor -- see its docstring), not the whole list every frame. */
  class StoryTimeline {
    constructor(container, steps, opts) {
      this.container = container;
      this.steps = steps || [];
      this.onStepClick = (opts && opts.onStepClick) || null;
      this._lastIdx = -1;
      this._render();
    }

    _render() {
      if (!this.steps.length) {
        this.container.innerHTML = `<p class="muted">No trips were dispatched in this plan \u2014 nothing to narrate.</p>`;
        this.stepEls = [];
        return;
      }
      const frag = document.createDocumentFragment();
      this.stepEls = this.steps.map((step, i) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "story-step";
        row.dataset.idx = String(i);
        if (step.vehicleId !== null && step.vehicleId !== undefined) {
          row.style.setProperty("--story-accent", Vis.colorForIdCss(step.vehicleId));
        }
        row.innerHTML = `<span class="story-body">${step.html}</span>` +
          `<span class="story-t">t=${fmt(step.t, 2)} hr</span>`;
        row.addEventListener("click", () => { if (this.onStepClick) this.onStepClick(step); });
        frag.appendChild(row);
        return row;
      });
      this.container.innerHTML = "";
      this.container.appendChild(frag);
    }

    /** Cheap per-frame update: marks steps up to time t as "done" and the
     * current one as "active", scrolling it into view. No-op if the
     * active step hasn't changed since the last call. */
    applyTime(t) {
      const idx = findIndexAtTime(this.steps, t);
      if (idx === this._lastIdx) return;
      if (idx > this._lastIdx) {
        for (let i = this._lastIdx + 1; i <= idx; i++) this.stepEls[i].classList.add("done");
      } else {
        for (let i = idx + 1; i <= this._lastIdx; i++) this.stepEls[i].classList.remove("done");
      }
      if (this._lastIdx >= 0 && this.stepEls[this._lastIdx]) this.stepEls[this._lastIdx].classList.remove("active");
      if (idx >= 0) {
        this.stepEls[idx].classList.add("active");
        this._scrollStepIntoView(this.stepEls[idx]);
      }
      this._lastIdx = idx;
    }
  }

  Vis.StoryTimeline = StoryTimeline;

  // Scroll ONLY the panel that holds the story, never the page. (scrollIntoView also
  // scrolled the window, which on a phone yanked the map out of view on every step.)
  Vis.StoryTimeline.prototype._scrollStepIntoView = function (el) {
    let p = el.parentElement;
    while (p && p.scrollHeight <= p.clientHeight + 1) p = p.parentElement;
    if (!p || p === document.body || p === document.documentElement) return;
    const r = el.getBoundingClientRect(), pr = p.getBoundingClientRect();
    if (r.top < pr.top) p.scrollBy({ top: r.top - pr.top - 8, behavior: "smooth" });
    else if (r.bottom > pr.bottom) p.scrollBy({ top: r.bottom - pr.bottom + 8, behavior: "smooth" });
  };
