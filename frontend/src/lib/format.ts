export function fmt(n: number | null | undefined, digits = 0): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "–";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}
export function inr(n: number | null | undefined, digits = 0): string {
  return n === undefined || n === null || Number.isNaN(n) ? "–" : "₹" + fmt(n, digits);
}
