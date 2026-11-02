// frontend/vis/icons.js
// -------------------------------------------------------------------------
// Builds a tiny in-memory icon atlas for the map: a farmer/crop glyph, a
// delivery vehicle glyph, and a market/storefront glyph, drawn as vector
// shapes on a <canvas>. This project's frontend has no build step or CDN
// dependency (see logisticsMap.js's header comment), so icons are drawn
// here instead of loading external image assets -- works fully offline,
// same as the rest of the map.
//
// Each icon is a solid white silhouette on a transparent background.
// deck.gl's IconLayer, given `mask: true` in the mapping, uses the alpha
// channel of the source pixels as a coverage mask and tints it per-feature
// with getColor -- so the SAME icon shape is reused for every status color
// (vehicle color, trip color, unserved red, market amber) exactly the way
// the plain-dot layers already assign color today. This file only draws
// shapes; it carries no solution/status/color logic of its own.
import { Vis } from "./namespace.js";

  const ICON_PX = 64; // each icon's square in the atlas, in source pixels
  const ICON_NAMES = ["farmer", "vehicle", "market"];

  // Older engines lack CanvasRenderingContext2D.roundRect (Chrome <99,
  // Safari <16) -- a tiny manual fallback so icon drawing never throws on
  // an older browser instead of silently leaving the map without icons.
  function roundRectPath(ctx, x, y, w, h, r) {
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, r);
      return;
    }
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // ---- farmer: a sprouting plant -- reads as "produce", not a generic pin
  function drawFarmerIcon(ctx, s) {
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#fff";
    ctx.lineCap = "round";
    ctx.lineWidth = s * 0.09;
    ctx.beginPath();
    ctx.moveTo(s * 0.5, s * 0.86);
    ctx.lineTo(s * 0.5, s * 0.42);
    ctx.stroke();
    // left leaf
    ctx.beginPath();
    ctx.moveTo(s * 0.5, s * 0.55);
    ctx.quadraticCurveTo(s * 0.16, s * 0.50, s * 0.20, s * 0.20);
    ctx.quadraticCurveTo(s * 0.50, s * 0.27, s * 0.5, s * 0.55);
    ctx.fill();
    // right leaf (mirrored)
    ctx.beginPath();
    ctx.moveTo(s * 0.5, s * 0.55);
    ctx.quadraticCurveTo(s * 0.84, s * 0.50, s * 0.80, s * 0.20);
    ctx.quadraticCurveTo(s * 0.50, s * 0.27, s * 0.5, s * 0.55);
    ctx.fill();
    // soil mound at the base
    ctx.beginPath();
    ctx.ellipse(s * 0.5, s * 0.86, s * 0.24, s * 0.075, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  // ---- vehicle: cab + cargo box + wheels -- reads as "truck", not a dot
  function drawVehicleIcon(ctx, s) {
    ctx.fillStyle = "#fff";
    roundRectPath(ctx, s * 0.08, s * 0.36, s * 0.52, s * 0.32, s * 0.045);
    ctx.fill();
    roundRectPath(ctx, s * 0.58, s * 0.44, s * 0.30, s * 0.24, s * 0.035);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(s * 0.26, s * 0.74, s * 0.095, 0, Math.PI * 2);
    ctx.arc(s * 0.68, s * 0.74, s * 0.095, 0, Math.PI * 2);
    ctx.fill();
  }

  // ---- market: storefront roof + awning + doorway cut-out
  function drawMarketIcon(ctx, s) {
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.moveTo(s * 0.15, s * 0.42);
    ctx.lineTo(s * 0.50, s * 0.15);
    ctx.lineTo(s * 0.85, s * 0.42);
    ctx.closePath();
    ctx.fill();
    roundRectPath(ctx, s * 0.22, s * 0.42, s * 0.56, s * 0.43, s * 0.03);
    ctx.fill();
    // doorway: punch a transparent notch out of the storefront body
    ctx.globalCompositeOperation = "destination-out";
    roundRectPath(ctx, s * 0.43, s * 0.60, s * 0.14, s * 0.25, s * 0.02);
    ctx.fill();
    ctx.globalCompositeOperation = "source-over";
  }

  const DRAWERS = { farmer: drawFarmerIcon, vehicle: drawVehicleIcon, market: drawMarketIcon };

  /** Draws the atlas once and returns { atlas: <data URI>, mapping }, ready
   * to hand straight to deck.gl's IconLayer as iconAtlas/iconMapping. A
   * data URI (rather than the raw canvas) is the most broadly-supported
   * form for iconAtlas across deck.gl versions. */
  Vis.buildIconAtlas = function () {
    const canvas = document.createElement("canvas");
    canvas.width = ICON_PX * ICON_NAMES.length;
    canvas.height = ICON_PX;
    const ctx = canvas.getContext("2d");
    const mapping = {};
    ICON_NAMES.forEach((name, i) => {
      ctx.save();
      ctx.translate(i * ICON_PX, 0);
      DRAWERS[name](ctx, ICON_PX);
      ctx.restore();
      mapping[name] = { x: i * ICON_PX, y: 0, width: ICON_PX, height: ICON_PX, mask: true };
    });
    return { atlas: canvas.toDataURL(), mapping };
  };
