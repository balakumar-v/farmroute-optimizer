import type { ChangeReason, ChangeRequest, ChangeStatus, PlanDiff } from "./api";

export const REASONS: { code: ChangeReason; label: string }[] = [
  { code: "too_late", label: "Too late" },
  { code: "not_possible", label: "Not possible" },
  { code: "capacity", label: "No space in the trucks" },
  { code: "other", label: "Other" },
];

export const STATUS_FILTERS: { id: ChangeStatus; label: string }[] = [
  { id: "pending", label: "Waiting for you" },
  { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
  { id: "withdrawn", label: "Withdrawn by farmer" },
  { id: "expired", label: "Expired" },
];

export const reasonLabel = (c: ChangeReason | null) => REASONS.find((r) => r.code === c)?.label ?? "";

/** Same members, in any order. */
export function sameIds(a: Iterable<number>, b: Iterable<number>): boolean {
  const x = new Set(a), y = new Set(b);
  return x.size === y.size && [...x].every((v) => y.has(v));
}

/** What the farmer typed. The form fallback stores "[form]". The text is untrusted: render it as text, never as HTML. */
export const rawText = (r: Pick<ChangeRequest, "raw_text">) => (r.raw_text === "[form]" ? "Used the form" : r.raw_text);

export interface PreviewRow { farmerId: number; asked: boolean; why: string[]; payoutChange: number }

/** The farmers a preview would move: the ones who asked first, then everyone else by how much their payout moves. */
export function previewRows(diff: PlanDiff, requested: number[]): PreviewRow[] {
  const ask = new Set(requested);
  return diff.changed
    .map((c) => ({ farmerId: c.farmer_id, asked: ask.has(c.farmer_id), why: c.why, payoutChange: c.payout_change_inr }))
    .sort((a, b) => Number(b.asked) - Number(a.asked) || (a.asked ? a.farmerId - b.farmerId : Math.abs(b.payoutChange) - Math.abs(a.payoutChange) || a.farmerId - b.farmerId));
}

/** "just now", "5 min ago", "3 h ago", then the date. `sec` is unix seconds, as the backend stores it. */
export function whenText(sec: number, nowMs: number = Date.now()): string {
  const m = Math.floor((nowMs - sec * 1000) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  if (m < 60 * 24) return `${Math.floor(m / 60)} h ago`;
  return new Date(sec * 1000).toLocaleDateString();
}

export const rupees = (v: number) => `${v < 0 ? "-" : v > 0 ? "+" : ""}Rs ${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
