import { describe, expect, it } from "vitest";
import { clock12 } from "./format";

describe("clock12", () => {
  it("hour 0 is 12:00 AM", () => expect(clock12(0).text).toBe("12:00 AM"));
  it("handles AM, noon and PM", () => {
    expect(clock12(6.5).text).toBe("6:30 AM");
    expect(clock12(12).text).toBe("12:00 PM");
    expect(clock12(14.25).text).toBe("2:15 PM");
    expect(clock12(23.99).text).toBe("11:59 PM");
  });
  it("rolls past midnight with a day count", () => {
    const c = clock12(25.5);
    expect(c.text).toBe("1:30 AM");
    expect(c.day).toBe(1);
  });
  it("is safe for bad input", () => expect(clock12(NaN).text).toBe("12:00 AM"));
});
