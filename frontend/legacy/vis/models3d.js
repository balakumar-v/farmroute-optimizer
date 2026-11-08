// frontend/vis/models3d.js
// -------------------------------------------------------------------------
// Builds actual recognizable low-poly 3D shapes -- a truck (cargo box + cab
// + wheels), a market stall (walls + a wider overhanging roof slab), and a
// small pile of produce crates -- for 3D mode, by composing several
// deck.gl PolygonLayer instances with `extruded: true`. Deliberately NOT
// using SimpleMeshLayer/custom GPU mesh buffers: PolygonLayer's extrusion
// (a 2D footprint given a height) is a well-documented, stable deck.gl
// feature, and a floating part (the stall's roof) is achieved by giving
// that footprint's ring vertices a base altitude (the z in [lng,lat,z]) --
// extrusion then runs from that altitude up to altitude + elevation. Both
// are standard, no custom shaders or raw vertex buffers required.
//
// All sizes here are deliberately exaggerated "toy model" scale (a "6 m"
// truck rendered ~140 m across), matching the rest of this map's existing
// convention of stylized, not true-to-life, marker sizes (the farmer disc
// is already 95 m, the market disc 160 m) -- at real-world scale these
// would be sub-pixel at any zoom level a viewer would actually use.
(function () {
  "use strict";
  const Vis = (window.Vis = window.Vis || {});

  const M_PER_DEG_LAT = 111320;

  function offsetLngLat(lng, lat, dxEastM, dyNorthM) {
    const dLat = dyNorthM / M_PER_DEG_LAT;
    const dLng = dxEastM / (M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180));
    return [lng + dLng, lat + dLat];
  }

  // Rotates a local (right, forward) offset by a compass heading (degrees,
  // clockwise from north) into a (east, north) offset. heading=0 means
  // "forward" points north and "right" points east, matching a vehicle
  // icon's natural resting orientation.
  function rotateToCompass(xRight, yForward, headingDeg) {
    const rad = (headingDeg * Math.PI) / 180;
    const east = xRight * Math.cos(rad) + yForward * Math.sin(rad);
    const north = -xRight * Math.sin(rad) + yForward * Math.cos(rad);
    return [east, north];
  }

  /** Local (right,forward) box corners, centered at (cx,cy), full width/length. */
  function boxLocal(cx, cy, widthRight, lengthForward) {
    const hw = widthRight / 2, hl = lengthForward / 2;
    return [[cx - hw, cy - hl], [cx + hw, cy - hl], [cx + hw, cy + hl], [cx - hw, cy + hl]];
  }

  /** Projects local (right,forward[,z]) corners to real [lng,lat,z] at a heading. */
  function project(lng, lat, headingDeg, localCorners, baseZ) {
    return localCorners.map(([x, y, z]) => {
      const [east, north] = rotateToCompass(x, y, headingDeg);
      const [lo, la] = offsetLngLat(lng, lat, east, north);
      return [lo, la, z !== undefined ? z : (baseZ || 0)];
    });
  }

  // ---- truck: cargo box (rear) + cab (front) + 4 wheels, heading-aware ---
  const TRUCK = {
    cargo: { local: boxLocal(0, -18, 46, 78), height: 52 },
    cab: { local: boxLocal(0, 40, 40, 34), height: 36 },
    wheelOffsets: [[-19, -46], [19, -46], [-17, 25], [17, 25]],
    wheelSize: 13, wheelHeight: 11,
  };

  Vis.vehicleFootprints = function (lng, lat, headingDeg) {
    const h = headingDeg || 0;
    return {
      cargo: project(lng, lat, h, TRUCK.cargo.local),
      cargoHeight: TRUCK.cargo.height,
      cab: project(lng, lat, h, TRUCK.cab.local),
      cabHeight: TRUCK.cab.height,
      wheels: TRUCK.wheelOffsets.map(([x, y]) => project(lng, lat, h, boxLocal(x, y, TRUCK.wheelSize, TRUCK.wheelSize))),
      wheelHeight: TRUCK.wheelHeight,
    };
  };

  // ---- market stall: waist-high walls + a wider roof slab floating on top
  const STALL = {
    // Shifted east of the market's true coordinate: that coordinate is where
    // a truck parks to sell, so a stall centered on it would swallow the
    // truck (and any camera following it) instead of letting it pull up
    // beside the stall.
    wall: { local: boxLocal(150, 20, 120, 120), height: 62 },
    roof: { local: boxLocal(150, 20, 160, 160), height: 14 },
  };

  Vis.marketFootprints = function (lng, lat) {
    return {
      wall: project(lng, lat, 0, STALL.wall.local),
      wallHeight: STALL.wall.height,
      roof: project(lng, lat, 0, STALL.roof.local, STALL.wall.height), // base z = top of the wall
      roofHeight: STALL.roof.height,
    };
  };

  // ---- farmer marker: a small pile of produce crates, deterministically
  // jittered per farmer id so a cluster of farmers doesn't look identical.
  Vis.farmerFootprints = function (lng, lat, seed) {
    const jitter = (n) => (((seed * 97 + n * 131) % 23) / 23 - 0.5) * 30;
    const crates = [
      { cx: 0 + jitter(1), cy: 0 + jitter(2), w: 34, l: 34, h: 26, rot: (seed * 41) % 30 },
      { cx: 14 + jitter(3), cy: 10 + jitter(4), w: 26, l: 26, h: 20, rot: (seed * 67) % 40 },
    ];
    return crates.map((c) => ({
      polygon: project(lng, lat, c.rot, boxLocal(c.cx, c.cy, c.w, c.l)),
      height: c.h,
    }));
  };
})();
