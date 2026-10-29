import { describe, expect, it } from "vitest";
import { Vis } from "./index";

// One vehicle, one trip: dispatch -> pick up farmer 7 -> pick up farmer 9 -> deliver to market 2 -> complete.
const events = [
  { type: "dispatch", timestamp: 1, tripId: "t1", vehicleId: 1, loadChangeKg: 0 },
  { type: "arrive_farmer", timestamp: 2, tripId: "t1", vehicleId: 1, locationId: 7, lat: 25.0, lng: 84.0 },
  { type: "pickup", timestamp: 2, tripId: "t1", vehicleId: 1, locationId: 7, loadChangeKg: 100 },
  { type: "arrive_farmer", timestamp: 3, tripId: "t1", vehicleId: 1, locationId: 9, lat: 25.1, lng: 84.1 },
  { type: "pickup", timestamp: 3, tripId: "t1", vehicleId: 1, locationId: 9, loadChangeKg: 50 },
  { type: "arrive_market", timestamp: 5, tripId: "t1", vehicleId: 1, locationId: 2, lat: 25.3, lng: 84.3 },
  { type: "delivery", timestamp: 5, tripId: "t1", vehicleId: 1, locationId: 2, loadChangeKg: -150 },
  { type: "complete", timestamp: 5, tripId: "t1", vehicleId: 1, loadChangeKg: 0 },
];
const routes = [{ id: "t1", vehicleId: 1, totalQtyKg: 150 }];
const make = () => new Vis.SimulationEngine(events, routes);

describe("SimulationEngine", () => {
  it("spans first to last event", () => {
    const e = make();
    expect(e.minT).toBe(1);
    expect(e.maxT).toBe(5);
    expect(e.t).toBe(1);
  });

  it("accumulates visited farmers and markets as time advances", () => {
    const e = make();
    e.seek(2.5);
    let s = e.snapshot();
    expect([...s.visitedFarmerIds as Set<number>]).toEqual([7]);
    expect((s.visitedMarketIds as Set<number>).size).toBe(0);
    e.seek(5);
    s = e.snapshot();
    expect([...s.visitedFarmerIds as Set<number>].sort()).toEqual([7, 9]);
    expect([...s.visitedMarketIds as Set<number>]).toEqual([2]);
  });

  it("scrubbing backwards un-visits (rescan) and visitedGeneration only bumps on change", () => {
    const e = make();
    e.seek(5);
    const g = e.snapshot().visitedGeneration;
    e.seek(5);
    expect(e.snapshot().visitedGeneration).toBe(g);
    e.seek(1.5);
    const s = e.snapshot();
    expect((s.visitedFarmerIds as Set<number>).size).toBe(0);
    expect(s.visitedGeneration).toBeGreaterThan(g);
  });

  it("interpolates the vehicle between stops and tracks load", () => {
    const e = make();
    e.seek(4);
    const [v] = e.snapshot().vehiclePositions as Array<{ lat: number; lng: number; loadKg: number }>;
    expect(v.lat).toBeGreaterThan(25.1);
    expect(v.lat).toBeLessThan(25.3);
    expect(v.loadKg).toBe(150);
  });

  it("clamps seeks and reports progress", () => {
    const e = make();
    e.seek(99);
    expect(e.t).toBe(5);
    expect(e.progress).toBe(1);
    e.seekProgress(0.5);
    expect(e.t).toBeCloseTo(3, 5);
    e.reset();
    expect(e.t).toBe(1);
  });

  it("notifies listeners and supports unsubscribe", () => {
    const e = make();
    let n = 0;
    const off = e.on(() => n++);
    e.seek(2);
    off();
    e.seek(3);
    expect(n).toBe(1);
  });
});

// Road-following: farmer 7 (25.0,84.0) -> farmer 9 (25.1,84.1) travels east along y=25.0, then north along x=84.1,
// instead of the straight diagonal. Leg 2 (farmer 9 -> market) has no road data, so it stays a straight line.
const roadRoutes = [{
  id: "t1", vehicleId: 1, totalQtyKg: 150,
  roadLegs: [
    { coordinates: [[84.0, 25.0], [84.1, 25.0], [84.1, 25.1]], distanceKm: 20 },
    { coordinates: [[84.1, 25.1], [84.3, 25.3]], distanceKm: 30 },
  ],
}];
// Corner sits at 0.1deg east * cos(25deg) = 0.0906 of 0.1906 total -> 47.5% of the way, i.e. t = 2 + 0.475.
const CORNER_FRAC = (0.1 * Math.cos(25 * Math.PI / 180)) / (0.1 * Math.cos(25 * Math.PI / 180) + 0.1);

describe("SimulationEngine with road geometry", () => {
  const eng = () => new Vis.SimulationEngine(events, roadRoutes);
  const at = (e: ReturnType<typeof eng>, t: number) => e.positionOfTrip("t1", t) as { lat: number; lng: number; heading: number };

  it("follows the road corner instead of cutting across", () => {
    const e = eng();
    const p = at(e, 2 + CORNER_FRAC);
    expect(p.lat).toBeCloseTo(25.0, 3);
    expect(p.lng).toBeCloseTo(84.1, 3);
    // the straight-line model would be at the diagonal midpoint (25.05, 84.05) here
    const straight = at(new Vis.SimulationEngine(events, routes), 2.5);
    expect(straight.lat).toBeCloseTo(25.05, 3);
  });

  it("heads east before the corner and north after it", () => {
    const e = eng();
    expect(at(e, 2.2).heading).toBeCloseTo(90, 0);
    expect(at(e, 2.8).heading).toBeCloseTo(0, 0);
  });

  it("is exact at the stops and monotonic in distance along the road", () => {
    const e = eng();
    const s7 = at(e, 2), s9 = at(e, 3);
    expect([s7.lat, s7.lng]).toEqual([25.0, 84.0]);
    expect(s9.lat).toBeCloseTo(25.1, 6);
    expect(s9.lng).toBeCloseTo(84.1, 6);
    let prev = -1;
    for (let t = 2; t <= 3; t += 0.05) {
      const p = at(e, t);
      const d = (p.lng - 84.0) * Math.cos(25 * Math.PI / 180) + (p.lat - 25.0); // progress proxy along the L
      expect(d).toBeGreaterThanOrEqual(prev - 1e-9);
      prev = d;
    }
  });

  it("falls back to a straight line for a leg without road data", () => {
    const e = eng();
    const p = at(e, 4); // halfway between farmer 9 and the market
    expect(p.lat).toBeCloseTo(25.2, 3);
    expect(p.lng).toBeCloseTo(84.2, 3);
  });

  it("ignores roadLegs whose count does not match the stops (no road, no crash)", () => {
    const bad = [{ id: "t1", vehicleId: 1, totalQtyKg: 150, roadLegs: [{ coordinates: [[84.0, 25.0], [84.1, 25.0]], distanceKm: 1 }] }];
    const e = new Vis.SimulationEngine(events, bad);
    const p = e.positionOfTrip("t1", 2.5) as { lat: number };
    expect(p.lat).toBeCloseTo(25.05, 3);
  });
});


describe("route details panel distance wording", () => {
  const render = (route: Record<string, unknown>) => {
    const container = { innerHTML: "" } as unknown as HTMLElement;
    const solution = { routes: [{ id: "t1", vehicleId: 1, farmerIds: [7, 9], marketIds: [1], stops: [], distanceKm: 61.2, ...route }], vehicles: [{ id: 1 }], farmers: [], markets: [] };
    (Vis as unknown as { renderDetailsPanel: (...a: unknown[]) => void }).renderDetailsPanel(container, { type: "route", id: "t1" }, solution, null);
    return container.innerHTML;
  };

  it("says the plan used road distances and shows road km when on roads", () => {
    const html = render({ geometry: "road", roadDistanceKm: 64.5, roadOffRoadKm: 2.1, roadProvider: "osrm", distanceBasis: "road_matrix" });
    expect(html).toContain("Road distance");
    expect(html).toContain("64.5 km");
    expect(html).toContain("optimized on measured road distances");
  });

  it("stays honest for a straight-line plan with no road shape loaded", () => {
    const html = render({ geometry: "straight_line", distanceBasis: "straight" });
    expect(html).not.toContain("Road distance");
    expect(html).toContain("optimized on straight-line distances");
  });
});
