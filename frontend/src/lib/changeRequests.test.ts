import { describe, expect, it } from "vitest";
import type { PlanDiff } from "./api";
import { previewRows, rawText, reasonLabel, rupees, sameIds, whenText } from "./changeRequests";

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
