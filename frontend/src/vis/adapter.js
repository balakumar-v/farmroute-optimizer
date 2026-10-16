// frontend/vis/adapter.js
// -------------------------------------------------------------------------
// Thin client-side consumer of GET /plan/{id}/visualization. The real
// adapter work (pools -> routes/events/farmers/vehicles/markets) happens
// backend-side in visualization_adapter.py -- this file does NOT contain
// optimization or routing logic. Its only two jobs:
//   1. fetch() the endpoint and surface errors the way app.js's api() does
//   2. deterministic color assignment, which is a presentation concern and
//      belongs in the frontend, not the backend adapter.
//
// Exposes window.Vis (created here, extended by the other vis/*.js files).

import { Vis } from "./namespace.js";

  Vis.ALGO_KEYS = ["integrated_logistics_optimization", "individual_transport", "proximity_pooling"];
  Vis.ALGO_LABELS = {
    integrated_logistics_optimization: "Our System (ILO)",
    individual_transport: "Individual Transport",
    proximity_pooling: "Proximity Pooling",
  };

  Vis.EVENT_STAGE = {
    dispatch: 6, arrive_farmer: 6, pickup: 6,
    arrive_market: 7, delivery: 7, complete: 7,
  };

  /** GET /plan/{planId}/visualization. Throws Error with a readable message
   * on failure, same convention app.js's api() uses. */
  Vis.fetchVisualization = async function (apiBase, planId) {
    if (!apiBase) throw new Error("Set the backend API base URL on the Data entry tab first.");
    if (planId === null || planId === undefined) throw new Error("No plan computed yet.");
    let res;
    try {
      res = await fetch(`${apiBase}/plan/${planId}/visualization`);
    } catch (e) {
      throw new Error(`Could not reach ${apiBase} -- is the backend running? (${e.message})`);
    }
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail; } catch (e) { /* ignore */ }
      throw new Error(`/plan/${planId}/visualization failed (${res.status})${detail ? ": " + JSON.stringify(detail) : ""}`);
    }
    return res.json();
  };

  Vis.fetchSensorReadings = async function (apiBase, poolId) {
    if (!apiBase) return [];
    const qs = poolId ? `?pool_id=${encodeURIComponent(poolId)}` : "";
    try {
      const res = await fetch(`${apiBase}/sensors/readings${qs}`);
      if (!res.ok) return [];
      return await res.json();
    } catch (e) {
      return [];
    }
  };

  // ---- deterministic color assignment ----------------------------------
  // Rule 20.9 in the brief: never a fixed color list that breaks past N
  // vehicles. A simple string hash -> hue keeps it stable and unbounded.
  function hashString(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) {
      h = (h * 31 + s.charCodeAt(i)) | 0;
    }
    return Math.abs(h);
  }

  function hslToRgb(h, s, l) {
    s /= 100; l /= 100;
    const k = (n) => (n + h / 30) % 12;
    const a = s * Math.min(l, 1 - l);
    const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return [Math.round(255 * f(0)), Math.round(255 * f(8)), Math.round(255 * f(4))];
  }

  /** Stable [r,g,b] (0-255) for any id (vehicle, pool, trip...). Same id
   * always gets the same color within a session; unbounded id space. */
  // A hand-picked categorical set. Hue-hashing sent vehicles 1, 3 and 4 to three
  // near-identical olives, so numeric ids now index a curated palette instead.
  // Red and yellow are deliberately absent: oxide red means "unserved" and
  // chrome yellow means "market" everywhere on the map.
  const VEHICLE_PALETTE = [
    [27, 111, 181],   // blue
    [30, 157, 106],   // green
    [194, 71, 143],   // magenta
    [122, 75, 184],   // violet
    [18, 163, 179],   // teal
    [138, 90, 60],    // umber
    [93, 130, 22],    // olive green
    [61, 79, 159],    // indigo
  ];
  Vis.VEHICLE_PALETTE = VEHICLE_PALETTE;
  Vis.colorForId = function (id, { sat = 60, light = 46 } = {}) {
    if (id === null || id === undefined) return [150, 150, 150];
    const str = String(id);
    const asInt = /^\d+$/.test(str) ? parseInt(str, 10) : null;
    if (asInt !== null && asInt >= 1 && asInt <= VEHICLE_PALETTE.length) return VEHICLE_PALETTE[asInt - 1].slice();
    // Past the curated set (or a non-numeric id): golden-angle hue, kept out of the red/yellow bands.
    const h = asInt !== null ? (asInt * 137.508) % 360 : hashString(str) % 360;
    return hslToRgb(95 + (h / 360) * 250, sat, light);
  };

  Vis.colorForIdCss = function (id, opts) {
    const [r, g, b] = Vis.colorForId(id, opts);
    return `rgb(${r},${g},${b})`;
  };

  Vis.STATUS_COLORS = {
    unserved: [179, 48, 26],        // oxide red, matches --red
    farmgate: [86, 97, 112],        // slate: sold to a trader at the doorstep (not a failure, so not red)
    unvisited: [150, 158, 166],
    visited: [27, 79, 156],         // enamel blue, matches --blue
  };
  Vis.MARKET_COLOR = [242, 183, 5]; // chrome yellow, matches --yellow
