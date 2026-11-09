import { describe, expect, it } from "vitest";
import type { ChangeLine, PlanDiff } from "./api";
import { clashingPairs, lineText, previewRows, rawText, reasonLabel, rupees, sameIds, whenText } from "./changeRequests";

const diff = (changed: { id: number; pay: number }[]): PlanDiff => ({
  farmers_changed: changed.length, farmers_unchanged: 0, farmers_only_in_old: [], farmers_only_in_new: [],
  changed: changed.map((c) => ({ farmer_id: c.id, why: [`payout ${c.pay > 0 ? "up" : "down"}`], payout_change_inr: c.pay })),
});

describe("previewRows", () => {
  it("lists the farmers who asked first, then the rest by how much their payout moves", () => {
    const rows = previewRows(diff([{ id: 9, pay: 5 }, { id: 4, pay: -300 }, { id: 2, pay: 40 }, { id: 7, pay: 0.5 }]), [7, 2]);
    expect(rows.map((r) => [r.farmerId, r.asked])).toEqual([[2, true], [7, true], [4, false], [9, false]]);
  });
  it("marks nobody as asking when the preview moved only other farmers", () => {
    expect(previewRows(diff([{ id: 1, pay: 10 }]), [5]).every((r) => !r.asked)).toBe(true);
  });
});

describe("sameIds", () => {
  it("ignores order and duplicates, and tells different sets apart", () => {
    expect(sameIds([1, 2, 3], [3, 1, 2])).toBe(true);
    expect(sameIds([1, 2], [1, 2, 3])).toBe(false);
    expect(sameIds([], [])).toBe(true);
    expect(sameIds(new Set([4]), [5])).toBe(false);
  });
});

describe("text helpers", () => {
  it("names the form fallback and leaves a farmer's own words alone", () => {
    expect(rawText({ raw_text: "[form]" })).toBe("Used the form");
    expect(rawText({ raw_text: "<b>100 kg</b> less" })).toBe("<b>100 kg</b> less");
  });
  it("labels reasons, and returns nothing for none", () => {
    expect(reasonLabel("too_late")).toBe("Too late");
    expect(reasonLabel(null)).toBe("");
  });
  it("says how long ago", () => {
    const now = Date.parse("2026-11-07T12:00:00Z");
    expect(whenText(now / 1000 - 20, now)).toBe("just now");
    expect(whenText(now / 1000 - 5 * 60, now)).toBe("5 min ago");
    expect(whenText(now / 1000 - 3 * 3600, now)).toBe("3 h ago");
  });
  it("formats a payout change with its sign", () => {
    expect(rupees(1234.4)).toBe("+Rs 1,234");
    expect(rupees(-80)).toBe("-Rs 80");
    expect(rupees(0)).toBe("Rs 0");
  });
});

describe("v2: next-day times, leaving the plan, clashes", () => {
  const line = (o: Partial<ChangeLine>): ChangeLine => ({ field: "ready_hr", label: "Ready time", from: "06:00", to: "06:30", from_day: 0, to_day: 0, ...o });
  it("shows a next-day time with its day and a plain time without one", () => {
    expect(lineText(line({}))).toBe("Ready time: 06:00 \u2192 06:30");
    expect(lineText(line({ to_day: 1 }))).toBe("Ready time: 06:00 \u2192 06:30 (+1 day)");
    expect(lineText(line({ to_day: 2 }))).toBe("Ready time: 06:00 \u2192 06:30 (+2 days)");
    expect(lineText(line({ field: "qty_kg", label: "Quantity", from: "400 kg", to: "300 kg" }))).toBe("Quantity: 400 kg \u2192 300 kg");
  });
  it("says in words when a farmer leaves or rejoins the plan", () => {
    expect(lineText(line({ field: "active", label: "Participation", from: "in", to: "out" }))).toMatch(/Leaves the plan/);
    expect(lineText(line({ field: "active", label: "Participation", from: "out", to: "in" }))).toMatch(/Rejoins the plan/);
  });
  it("finds selected requests that cannot be approved together, once per pair", () => {
    const reqs = [{ id: 1, overlaps: [2] }, { id: 2, overlaps: [1] }, { id: 3, overlaps: [] }, { id: 4, overlaps: [1] }];
    expect(clashingPairs([1, 2, 3], reqs)).toEqual([[1, 2]]);
    expect(clashingPairs([1, 3], reqs)).toEqual([]);
    expect(clashingPairs([1, 2, 4], reqs)).toEqual([[1, 2], [1, 4]]);
    expect(clashingPairs([], reqs)).toEqual([]);
  });
  it("lists farmers who leave or join the plan in a preview, asked ones first", () => {
    const d: PlanDiff = { farmers_changed: 1, farmers_unchanged: 5, farmers_only_in_old: [7], farmers_only_in_new: [9],
      changed: [{ farmer_id: 3, why: ["payout down"], payout_change_inr: -40 }] };
    const rows = previewRows(d, [7]);
    expect(rows.map((r) => [r.farmerId, r.asked, r.why[0]])).toEqual([[7, true, "Leaves the plan"], [3, false, "payout down"], [9, false, "Joins the plan"]]);
  });
});
