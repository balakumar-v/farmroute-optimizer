// frontend/vis/panels.js
// -------------------------------------------------------------------------
// Renders the "Why?" details panel (section 11 of the brief), the
// baseline-vs-optimized comparison table (section 12), and stage blurbs
// (section 10). Pure DOM rendering from data the backend already computed
// -- see the inline comments below for exactly which numbers are real
// (reported by the optimizer) vs. derived for display (clearly tagged).
(function () {
  "use strict";
  const Vis = (window.Vis = window.Vis || {});

  function fmt(n, digits) {
    if (n === undefined || n === null || Number.isNaN(n)) return "\u2013";
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 0 : digits });
  }
  function inr(n, digits) { return `\u20B9${fmt(n, digits)}`; }
  function kg(n, digits) { return `${fmt(n, digits === undefined ? 1 : digits)} kg`; }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  Vis.STAGE_BLURBS = {
    1: "Every farmer who registered produce for this planning cycle.",
    2: "Farmers grouped into pooling clusters that will share one vehicle trip. Lines connect each farmer to its pool.",
    3: "Each pool matched to a specific vehicle from the fleet \u2014 color now shows which vehicle serves which farmers.",
    4: "Markets added to the map. The optimizer decides which market(s) each pool's produce is allocated to.",
    5: "The planned pickup-then-delivery route for every dispatched vehicle (straight-line display, not real roads).",
    6: "Vehicles move along their routes and pick up produce as they go \u2014 press Play under the map, and follow along in the Story panel.",
    7: "Final deliveries. The Plan tab has the summary numbers for what this run achieved.",
  };

  function findRoute(solution, tripId) { return solution.routes.find((r) => r.id === tripId); }
  function findVehicle(solution, vehicleId) { return solution.vehicles.find((v) => v.id === vehicleId); }
  function findFarmer(solution, farmerId) { return solution.farmers.find((f) => f.id === farmerId); }
  function findMarket(solution, marketId) { return solution.markets.find((m) => m.id === marketId); }

  function checkRow(ok, label) {
    return `<div class="check-row ${ok ? "check-ok" : "check-bad"}"><svg class="i" aria-hidden="true"><use href="#i-${ok ? "check" : "close"}"/></svg><span>${esc(label)}</span></div>`;
  }

  // ---- farmer -------------------------------------------------------------
  function renderFarmer(solution, farmer, simSnapshot) {
    const route = farmer.tripId ? findRoute(solution, farmer.tripId) : null;
    const vehicle = route ? findVehicle(solution, route.vehicleId) : null;
    let html = `<h4>Farmer ${farmer.id}</h4><dl>
      <dt>Crop</dt><dd>${esc(farmer.crop)}</dd>
      <dt>Quantity</dt><dd>${kg(farmer.loadKg)}</dd>
      <dt>Pickup window</dt><dd>${fmt(farmer.timeWindow.start, 1)}\u2013${fmt(farmer.timeWindow.end, 1)} hr</dd>
      <dt>Needs refrigeration</dt><dd>${farmer.needsRefrigeration ? "Yes" : "No"}</dd>
    </dl>`;
    if (farmer.served && route && vehicle) {
      html += `<div class="check-row check-ok"><svg class="i" aria-hidden="true"><use href="#i-check"/></svg><span>Served by Vehicle ${vehicle.id} (${esc(vehicle.typeName)}), trip ${route.id}</span></div>`;
      html += checkRow(route.totalQtyKg <= vehicle.capacityKg + 1e-6, "Pool weight fits the assigned vehicle's capacity");
      if (farmer.needsRefrigeration) {
        html += checkRow(!!vehicle.refrigerated, "Assigned vehicle is refrigerated");
      }
      html += `<p class="derived-note">Belongs to pooling group ${esc(route.id)} for this plan (a display grouping, not a persisted cluster id from the optimizer).</p>`;
    } else {
      html += `<div class="check-row check-bad"><svg class="i" aria-hidden="true"><use href="#i-close"/></svg><span>Never picked up \u2014 no vehicle in the fleet reached it within its pickup window under this plan.</span></div>`;
    }
    return html;
  }

  // ---- vehicle --------------------------------------------------------------
  function renderVehicle(solution, vehicle, simSnapshot) {
    const trips = vehicle.tripIds.map((tid) => findRoute(solution, tid)).filter(Boolean);
    let html = `<h4>Vehicle ${vehicle.id} \u2014 ${esc(vehicle.typeName)}</h4><dl>
      <dt>Capacity</dt><dd>${kg(vehicle.capacityKg)}</dd>
      <dt>Refrigerated</dt><dd>${vehicle.refrigerated ? "Yes" : "No"}</dd>
      <dt>Fixed cost</dt><dd>${inr(vehicle.fixedCost, 2)}</dd>
      <dt>Cost / km</dt><dd>${inr(vehicle.perKmCost, 2)}</dd>
      <dt>Trips today</dt><dd>${trips.length}</dd>
    </dl>`;
    const live = simSnapshot && simSnapshot.vehiclePositions.find((v) => v.vehicleId === vehicle.id);
    if (live) {
      const cap = live.capacityKg || vehicle.capacityKg;
      const pct = cap ? Math.min(100, (100 * live.loadKg) / cap) : 0;
      html += `<div class="check-row">Current load (this trip)</div>
        <div class="capacity-bar${pct > 100 ? " over" : ""}"><div style="width:${Math.min(100, pct)}%"></div></div>
        <p class="derived-note">${kg(live.loadKg)} of ${kg(cap)} on trip ${esc(live.tripId)} at t=${fmt(simSnapshot.t, 2)} hr</p>`;
    }
    if (trips.length) {
      html += `<p class="derived-note" style="margin-top:10px;">Trips this plan:</p><dl>`;
      for (const r of trips) {
        html += `<dt>${esc(r.id)}</dt><dd>${r.farmerIds.length} farmer(s), ${kg(r.totalQtyKg)}, net ${inr(r.netReturn, 0)}</dd>`;
      }
      html += `</dl>`;
    } else {
      html += `<p class="muted">Not dispatched in this plan.</p>`;
    }
    return html;
  }

  // ---- market ---------------------------------------------------------------
  function renderMarket(solution, market) {
    const crops = Object.keys(market.price);
    let html = `<h4>Market ${market.id}</h4><dl>`;
    for (const c of crops) {
      html += `<dt>${esc(c)} price</dt><dd>${inr(market.price[c], 2)}/kg</dd>`;
    }
    for (const c of crops) {
      html += `<dt>${esc(c)} capacity</dt><dd>${kg(market.capacityKg[c] || 0)}</dd>`;
    }
    html += `</dl>`;
    if (market.receivedKg) {
      html += `<p class="derived-note">Received this cycle <span class="data-tag live">exact</span></p><dl>`;
      const recCrops = Object.keys(market.receivedKg);
      if (recCrops.length === 0) html += `<dt>\u2013</dt><dd>Nothing allocated here in this plan</dd>`;
      for (const c of recCrops) html += `<dt>${esc(c)}</dt><dd>${kg(market.receivedKg[c])}</dd>`;
      html += `</dl>`;
    } else {
      html += `<p class="derived-note">Per-market received-kg breakdown isn't available for this algorithm's stored result <span class="data-tag estimated">aggregate only</span> \u2014 see the route panel for this pool's total revenue/unsold instead.</p>`;
    }
    return html;
  }

  // ---- route (the flagship "Why?" panel) -------------------------------------
  function renderRoute(solution, route) {
    const vehicle = findVehicle(solution, route.vehicleId);
    const farmerChain = route.farmerIds.map((fid) => `F${fid}`).join(", then ");
    const marketChain = route.marketIds.map((mid) => `M${mid}`).join(", ") || "\u2013";
    let html = `<h4>Trip ${esc(route.id)} \u2014 Vehicle ${route.vehicleId}</h4>
      <dl>
        <dt>Pickup order</dt><dd>${esc(farmerChain)}</dd>
        <dt>Delivered to</dt><dd>${esc(marketChain)}</dd>
        <dt>Total quantity</dt><dd>${kg(route.totalQtyKg)}</dd>
        <dt>Revenue</dt><dd>${inr(route.revenue)}</dd>
        <dt>Transport cost</dt><dd>${inr(route.transportCost)}</dd>
        <dt>Net return</dt><dd>${inr(route.netReturn)}</dd>
        <dt>Spoilage</dt><dd>${kg(route.spoilageLossKg)}</dd>
        <dt>Unsold at market</dt><dd>${kg(route.unsoldKg)}</dd>
        <dt>Distance <span class="data-tag estimated">derived</span></dt><dd>${fmt(route.distanceKm, 1)} km</dd>
      </dl>
      <p class="derived-note">Straight-line distance recomputed from stop coordinates (this project has no road-network data) \u2014 not a real road route.</p>`;

    if (vehicle) {
      html += checkRow(route.totalQtyKg <= vehicle.capacityKg + 1e-6, "Load within vehicle capacity");
      const needsRefrig = route.farmerIds.some((fid) => { const f = findFarmer(solution, fid); return f && f.needsRefrigeration; });
      if (needsRefrig) html += checkRow(!!vehicle.refrigerated, "Refrigeration-needing produce on a refrigerated vehicle");
    }

    if (route.marketAllocations) {
      html += `<p class="derived-note" style="margin-top:8px;">Per-market breakdown <span class="data-tag live">exact</span></p>
        <dl>`;
      for (const a of route.marketAllocations) {
        const priceTxt = a.price !== null && a.price !== undefined ? ` @ ${inr(a.price, 2)}/kg` : "";
        html += `<dt>M${a.market_id} \u00b7 ${esc(a.crop)}</dt><dd>${kg(a.kg)}${priceTxt}</dd>`;
      }
      html += `</dl>`;
    }
    return html;
  }

  Vis.renderDetailsPanel = function (container, selection, solution, simSnapshot) {
    if (!selection || !solution) {
      container.innerHTML = `<p class="muted">Click a farmer, vehicle, market or route on the map.</p>`;
      return;
    }
    let html = "";
    if (selection.type === "farmer") {
      const f = findFarmer(solution, selection.id);
      html = f ? renderFarmer(solution, f, simSnapshot) : "";
    } else if (selection.type === "vehicle") {
      const v = findVehicle(solution, selection.id);
      html = v ? renderVehicle(solution, v, simSnapshot) : "";
    } else if (selection.type === "market") {
      const m = findMarket(solution, selection.id);
      html = m ? renderMarket(solution, m) : "";
    } else if (selection.type === "route") {
      const r = findRoute(solution, selection.id);
      html = r ? renderRoute(solution, r) : "";
    }
    container.innerHTML = html || `<p class="muted">Nothing found for that selection.</p>`;
  };

  // ---- comparison panel (section 12) -----------------------------------------
  const METRIC_ROWS = [
    { key: "vehicles_used", label: "Vehicles used", digits: 0, better: null }, // how a plan is built, not how good it is
    { key: "total_distance_km", label: "Total distance (km)", digits: 1, better: "min", optional: true },
    { key: "total_transport_cost", label: "Transport cost", digits: 0, better: "min", money: true },
    { key: "pct_qty_served", label: "Produce served (%)", digits: 1, better: "max" },
    { key: "net_return", label: "Net return", digits: 0, better: "max", money: true },
    { key: "total_spoilage_kg", label: "Spoilage (kg)", digits: 1, better: "min" },
  ];

  Vis.renderComparisonPanel = function (container, solutionsByAlgo) {
    const keys = Object.keys(solutionsByAlgo);
    const rows = METRIC_ROWS.filter((m) => keys.some((k) => solutionsByAlgo[k].summary[m.key] !== undefined));
    let html = `<table><thead><tr><th>Metric</th>`;
    for (const k of keys) html += `<th>${esc(Vis.ALGO_LABELS[k] || k)}</th>`;
    html += `</tr></thead><tbody>`;
    for (const row of rows) {
      const values = keys.map((k) => solutionsByAlgo[k].summary[row.key]);
      const numeric = values.filter((v) => typeof v === "number");
      const allSame = numeric.every((v) => Math.abs(v - numeric[0]) < 1e-9);
      const best = numeric.length && row.better && !allSame ? (row.better === "max" ? Math.max(...numeric) : Math.min(...numeric)) : null;
      html += `<tr><td>${esc(row.label)}</td>`;
      for (const v of values) {
        const isBest = best !== null && typeof v === "number" && Math.abs(v - best) < 1e-9;
        const text = v === undefined ? "\u2013" : row.money ? inr(v, row.digits) : fmt(v, row.digits);
        html += `<td class="${isBest ? "best" : ""}">${text}</td>`;
      }
      html += `</tr>`;
    }
    html += `</tbody></table>`;
    container.innerHTML = html;
  };
})();
