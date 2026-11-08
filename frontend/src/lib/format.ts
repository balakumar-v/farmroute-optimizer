export function fmt(n: number | null | undefined, digits = 0): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "–";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}
export function inr(n: number | null | undefined, digits = 0): string {
  return n === undefined || n === null || Number.isNaN(n) ? "–" : "₹" + fmt(n, digits);
}

/** Plan hour (0 = 12:00 AM, may exceed 24 for trips that run past midnight) -> 12-hour clock parts. */
export function clock12(hours: number | null | undefined): { text: string; h: string; m: string; ap: "AM" | "PM"; day: number; angleH: number; angleM: number } {
  const t = Number.isFinite(hours as number) && (hours as number) > 0 ? (hours as number) : 0;
  const total = Math.floor(t * 60 + 1e-6);
  const day = Math.floor(total / 1440);
  const mins = total % 1440;
  const h24 = Math.floor(mins / 60), m = mins % 60;
  const ap = h24 < 12 ? "AM" : "PM";
  const h = String(h24 % 12 === 0 ? 12 : h24 % 12);
  const mm = String(m).padStart(2, "0");
  return { text: `${h}:${mm} ${ap}`, h, m: mm, ap, day,
    angleH: ((h24 % 12) + m / 60) * 30, angleM: m * 6 };
}
