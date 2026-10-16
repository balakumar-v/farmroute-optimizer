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
