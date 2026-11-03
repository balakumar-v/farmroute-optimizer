import { PRINT_CROPS, PRINT_STRINGS, type PrintLang } from "./printStrings";

/** One farmer's card exactly as the backend publishes it (GET /published/cards). Only the fields printing needs. */
export interface PublishedCard {
  farmer_id: number;
  crop: string;
  qty_kg: number;
  status: "hauled" | "farmgate" | "unserved";
  payout: { total_inr: number };
  trip: { pickup_eta: string | null; mandis: { id: string | number }[] } | null;
  changed?: unknown[] | null;
  doorstep_per_kg: number;
  fpo_phone?: string | null;
}
export interface PublishedCards { plan_id: number; published_at: string; cards: PublishedCard[] }
export type PerPage = 4 | 1;

const esc = (x: unknown) => String(x ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
/** Plan time "13:05" -> { t: "1:05", p: "PM" } (same hour as the card, just written in AM/PM). */
const to12 = (e: string) => { const m = /^(\d{1,2}):(\d{2})$/.exec(e); if (!m) return { t: e, p: "" }; const h = +m[1] % 24; return { t: `${h % 12 || 12}:${m[2]}`, p: h < 12 ? "AM" : "PM" }; };
const rs = (v: number) => "₹" + Math.round(v).toLocaleString("en-IN");
const LOCALE: Record<PrintLang, string> = { en: "en-IN", te: "te-IN", hi: "hi-IN", ta: "ta-IN" };

/** "5, 8-12, 20" -> Set{5,8,9,...,12,20}. Empty text = null (all farmers). Throws a readable message on bad input. */
export function parseIds(text: string): Set<number> | null {
  const t = text.trim();
  if (!t) return null;
  const out = new Set<number>();
  for (const part of t.split(/[\s,;]+/).filter(Boolean)) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(part);
    if (!m) throw new Error(`"${part}" is not a farmer ID or a range like 5-12.`);
    const a = +m[1], b = m[2] ? +m[2] : a;
    if (b < a || b - a > 5000) throw new Error(`"${part}" is not a valid range.`);
    for (let i = a; i <= b; i++) out.add(i);
  }
  return out;
}

function cardHtml(c: PublishedCard, lang: PrintLang, publishedAt: string): string {
  const L = PRINT_STRINGS[lang];
  const t = (k: string, v: Record<string, unknown> = {}) => (L[k] ?? PRINT_STRINGS.en[k] ?? "").replace(/\{(\w+)\}/g, (_: string, n: string) => String(v[n] ?? ""));
  const crop = esc(PRINT_CROPS[lang][c.crop] ?? c.crop);
  const mandi = esc(c.trip?.mandis?.[0]?.id ?? "");
  const total = rs(c.payout.total_inr);
  const eta12 = to12(c.trip?.pickup_eta ?? "");
  const eta = esc(eta12.p ? `${eta12.t} ${eta12.p}` : eta12.t);
  const hauled = c.status === "hauled", farmgate = c.status === "farmgate";
  const when = new Date(publishedAt).toLocaleString(LOCALE[lang], { dateStyle: "medium", timeStyle: "short" });
  const tag = (txt: string) => `<span class="tag">${esc(txt)}</span>`;

  const head = hauled
    ? `<div class="kick">${esc(t("comes"))}</div><div class="big">${esc(eta12.t)}<small>${eta12.p}</small></div><div class="sub">${t("takes", { kg: c.qty_kg, crop, m: mandi })}</div>`
    : farmgate
      ? `<div class="kick">${esc(t("doorK"))}</div><div class="mid">${esc(t("doorT"))}</div><div class="sub">${esc(t("doorB"))}</div>`
      : `<div class="kick">${esc(t("ntK"))}</div><div class="mid">${esc(t("ntT"))}</div><div class="sub">${t("ntB", { crop })}</div>`;
  const money = `<div class="money"><div class="lbl">${esc(t(hauled ? "recv" : farmgate ? "doorP" : "ntP"))}</div>
    <div class="amt">${esc(total)} ${tag(t(hauled ? "est" : "assumed"))}</div>${farmgate ? `<div class="lbl">${esc(t("perkg", { v: rs(c.doorstep_per_kg) }))}</div>` : ""}</div>`;
  const steps = hauled
    ? `<ol class="steps"><li><b>${esc(t("s1", { t: eta }))}</b><span>${esc(t("s1b"))}</span></li>
       <li><b>${esc(t("s2", { m: mandi }))}</b><span>${esc(t("s2b"))}</span></li>
       <li><b>${esc(t("s3", { v: total }))}</b><span>${esc(t("s3b"))}</span></li></ol>`
    : !farmgate ? `<div class="sub strong">${esc(t("askF"))}</div>` : "";
  const changed = c.changed && c.changed.length ? `<div class="chg">${esc(t("changed"))}</div>` : "";
  const phone = c.fpo_phone ? `<div class="call">${esc(t("call"))}: <b>${esc(c.fpo_phone)}</b></div>` : "";
  return `<section class="card" lang="${lang}"><div class="hd"><span>${esc(t("farmer"))} <b>${c.farmer_id}</b></span><span class="when">${esc(t("pub", { d: when }))}</span></div>
    <div class="top">${head}</div><div class="body">${changed}${money}${steps}</div>
    <div class="ft">${phone}<div class="note">${esc(t("note"))} ${esc(t("renew"))}</div></div></section>`;
}

const CSS = `
*{box-sizing:border-box}html,body{margin:0}
body{font-family:"Mukta","Noto Sans Telugu","Noto Sans Tamil","Nirmala UI","Latha","Gautami","Mangal","Noto Sans",system-ui,sans-serif;color:#14231B;background:#e9efeb;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.bar{position:sticky;top:0;background:#14231B;color:#fff;padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;font:600 15px/1.3 system-ui,sans-serif;z-index:5}
.bar button{font:700 15px system-ui,sans-serif;padding:8px 16px;border:0;border-radius:8px;background:#F2B84B;color:#14231B;cursor:pointer}
.page{width:210mm;height:297mm;margin:10px auto;background:#fff;padding:8mm;display:grid;gap:0;page-break-after:always;break-after:page}
.page.p4{grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr}.page.p1{grid-template-columns:1fr;grid-template-rows:1fr}
.card{border:.4mm dashed #8a9a90;padding:5mm;display:flex;flex-direction:column;gap:2.2mm;overflow:hidden;font-size:10.5pt;line-height:1.35;break-inside:avoid}
.p4 .card{font-size:9.8pt;padding:4.5mm;gap:2mm}.p4 .big{font-size:3em}.p4 .amt{font-size:1.7em}
.p1 .card{font-size:17pt;padding:14mm;gap:6mm}
.hd{display:flex;justify-content:space-between;gap:6px;font-size:.9em;border-bottom:.3mm solid #BFD0C6;padding-bottom:1.5mm}.when{font-size:.72em;color:#3E5247;text-align:right}
.top{background:#1E4D3A;color:#fff;border-radius:2.5mm;padding:3mm 4mm;display:flex;flex-direction:column;gap:1mm}
.kick{font-size:.95em;font-weight:600}.big{font-size:3.4em;line-height:1;font-weight:800}.big small{font-size:.38em;margin-left:.12em}.mid{font-size:1.9em;line-height:1.15;font-weight:800}.sub{font-size:.95em}.strong{font-weight:600}
.body{display:flex;flex-direction:column;gap:2.2mm;flex:1}
.chg{background:#FFF4D6;border-radius:2mm;padding:1.5mm 2.5mm;font-weight:600;font-size:.9em}
.lbl{font-size:.9em;color:#3E5247}.amt{font-size:1.9em;font-weight:800;line-height:1.15}
.tag{font-size:.4em;font-weight:600;border:.3mm solid #8A5A00;color:#8A5A00;border-radius:99px;padding:.2mm 1.8mm;vertical-align:middle;white-space:nowrap}
.steps{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:1.6mm;border-top:.3mm solid #BFD0C6;padding-top:2mm}
.steps li{display:flex;flex-direction:column}.steps b{font-size:.98em}.steps span{font-size:.85em;color:#3E5247}
.ft{margin-top:auto;border-top:.3mm solid #BFD0C6;padding-top:1.5mm}.call{font-size:.95em;font-weight:600}.call b{white-space:nowrap}.note{font-size:.68em;color:#3E5247;line-height:1.3;margin-top:.8mm}
@page{size:A4;margin:0}
@media print{body{background:#fff}.bar{display:none}.page{margin:0;box-shadow:none}}
`;

/** Full printable document: A4 pages of 4 (A6-sized, cut lines) or 1 card each. Opens the browser's print dialog,
 *  where "Save as PDF" gives the PDF. The browser does the text shaping, so Telugu/Tamil/Hindi render correctly. */
export function buildPrintHtml(data: PublishedCards, lang: PrintLang, perPage: PerPage, ids: Set<number> | null): { html: string; count: number } {
  const cards = data.cards.filter((c) => !ids || ids.has(c.farmer_id));
  const pages: string[] = [];
  for (let i = 0; i < cards.length; i += perPage) {
    pages.push(`<div class="page p${perPage}">${cards.slice(i, i + perPage).map((c) => cardHtml(c, lang, data.published_at)).join("")}</div>`);
  }
  const html = `<!doctype html><html lang="${lang}"><head><meta charset="utf-8"><title>Farmroute cards (${lang})</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Mukta:wght@400;600;800&family=Noto+Sans+Telugu:wght@500;800&family=Noto+Sans+Tamil:wght@500;800&display=swap" rel="stylesheet">
<style>${CSS}</style></head><body>
<div class="bar"><button onclick="window.print()">Print / Save as PDF</button><span>${cards.length} cards, ${pages.length} page${pages.length === 1 ? "" : "s"}. In the print dialog choose paper A4, margins None, and turn on Background graphics. Cut along the dashed lines.</span></div>
${pages.join("")}
<script>(function(){var done=false;function go(){if(done)return;done=true;setTimeout(function(){window.print()},400)}
window.addEventListener("load",function(){(document.fonts&&document.fonts.ready?document.fonts.ready:Promise.resolve()).then(go)});setTimeout(go,6000)})()</script>
</body></html>`;
  return { html, count: cards.length };
}

/** Open the print view in a new tab. Call this synchronously from the click so pop-up blockers allow it. */
export function openPrintWindow(): Window | null {
  const w = window.open("", "_blank");
  if (w) w.document.write("<p style='font:16px system-ui;padding:24px'>Preparing cards…</p>");
  return w;
}
export function writePrintWindow(w: Window, html: string) {
  w.document.open(); w.document.write(html); w.document.close();
}
