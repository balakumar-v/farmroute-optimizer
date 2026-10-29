import { PageHead, BusyButton, StaleBanner } from "../components/Shell";
import { ALGO_BLURB, ALGO_KEYS, ALGO_NAME } from "../lib/constants";
import { fmt, inr } from "../lib/format";
import type { AlgoKey, PlanResponse, PlanSummary, ViewName } from "../lib/types";
import { useApp } from "../state/store";
import { NoPlan } from "./PlanView";

interface Metric { label: string; key: keyof PlanSummary & string; f: (v: number) => string; best: "max" | "min" | null }

const METRICS: Metric[] = [
  { label: "Revenue", key: "total_revenue", f: (v) => inr(v), best: "max" },
  { label: "Transport cost", key: "total_transport_cost", f: (v) => inr(v), best: "min" },
  { label: "Net return (hauled trips)", key: "net_return", f: (v) => inr(v), best: "max" },
  { label: "Value of produce not hauled, at the assumed farm-gate price", key: "farmgate_revenue", f: (v) => inr(v), best: null },
  { label: "Farmer value (net return + farm-gate sales)", key: "net_return_incl_farmgate", f: (v) => inr(v), best: "max" },
  { label: "Farmer value per farmer", key: "net_return_per_farmer_incl_farmgate", f: (v) => inr(v), best: "max" },
  { label: "Net return per farmer (hauled only)", key: "net_return_per_farmer", f: (v) => inr(v), best: "max" },
  { label: "Produce sold at a market", key: "pct_qty_served", f: (v) => fmt(v, 1) + "%", best: "max" },
  { label: "Produce not hauled (sold at the farm gate)", key: "farmgate_kg", f: (v) => fmt(v, 1) + " kg", best: null },
  { label: "Spoilage in transit", key: "total_spoilage_kg", f: (v) => fmt(v, 1) + " kg", best: "min" },
  { label: "Unsold at market", key: "total_unsold_kg", f: (v) => fmt(v, 1) + " kg", best: "min" },
  { label: "Never got a truck", key: "total_unserved_no_vehicle_kg", f: (v) => fmt(v, 1) + " kg", best: "min" },
  { label: "Vehicles used", key: "vehicles_used", f: (v) => fmt(v), best: null },
  { label: "Pools formed", key: "pools_formed", f: (v) => fmt(v), best: null },
];

function Scoreboard({ plan }: { plan: PlanResponse }) {
  const sum = (k: AlgoKey): PlanSummary => plan[k]?.summary ?? {};
  const ilo = sum(ALGO_KEYS[0]);
  // The baselines let farmers sell at the farm gate, which plain "net return" scores as zero, so the headline is
  // net return PLUS farm-gate sales whenever the API provides it (older stored plans fall back).
  const hasFg = ALGO_KEYS.every((k) => sum(k).net_return_incl_farmgate !== undefined);
  const valueOf = (s: PlanSummary) => (hasFg ? s.net_return_incl_farmgate : s.net_return) || 0;
  const maxNet = Math.max(1, ...ALGO_KEYS.map((k) => valueOf(sum(k))));
  return (
    <div id="scoreboard" className="scoreboard">
      <div className="sb-head"><span>Approach</span><span>{hasFg ? "Farmer value (₹)" : "Net return (₹)"}</span><span>{hasFg ? "Sold at a market (%)" : "Produce sold (%)"}</span><span style={{ textAlign: "right" }}>ILO vs this</span></div>
      {ALGO_KEYS.map((k) => {
        const s = sum(k);
        const net = valueOf(s);
        const w = (Math.max(0, net) / maxNet) * 100;
        const pct = s.pct_qty_served ?? 0;
        const isIlo = k === ALGO_KEYS[0];
        let delta = <span className="sb-delta">{"–"}<small>reference</small></span>;
        if (!isIlo) {
          const diff = valueOf(ilo) - net;
          const rel = net !== 0 ? (diff / Math.abs(net)) * 100 : null;
          const cls = diff > 0.5 ? "up" : diff < -0.5 ? "down" : "";
          const word = diff > 0.5 ? "more" : diff < -0.5 ? "less" : "same";
          const note = word === "same" ? (hasFg ? "equal value" : "equal net return") : `ILO ${hasFg ? "earns" : "nets"} ${word}` + (rel !== null ? ` (${fmt(Math.abs(rel), 0)}%)` : "");
          delta = <span className={`sb-delta ${cls}`}>{diff > 0.5 ? "+" : diff < -0.5 ? "−" : ""}{inr(Math.abs(diff))}<small>{note}</small></span>;
        }
        return (
          <div key={k} className={"sb-row" + (isIlo ? " is-ilo" : "")}>
            <div className="sb-name"><h2>{ALGO_NAME[k]}</h2><p>{ALGO_BLURB[k]}</p></div>
            <div className="sb-col"><div className="sb-cap">{hasFg ? "Farmer value" : "Net return"}</div><div className="bar-cell"><div className="bar-track"><div className={"bar-fill" + (net < 0 ? " neg" : "")} style={{ width: `${w}%` }} /></div><span className="bar-val">{inr(net)}</span></div></div>
            <div className="sb-col"><div className="sb-cap">{hasFg ? "Sold at a market" : "Produce sold"}</div><div className="bar-cell"><div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, pct)}%` }} /></div><span className="bar-val">{fmt(pct, 1)}%</span></div></div>
            {delta}
          </div>
        );
      })}
    </div>
  );
}

function Breakdown({ plan }: { plan: PlanResponse }) {
  const sum = (k: AlgoKey): PlanSummary => plan[k]?.summary ?? {};
  const hasFg = ALGO_KEYS.every((k) => sum(k).net_return_incl_farmgate !== undefined);
  const ilo = plan.integrated_logistics_optimization;
  const beh = plan.realistic_baselines?.assumptions?.behaviour;
  const disc = ilo.farmgate_discount;
  const metrics = METRICS.filter((m) => ALGO_KEYS.some((k) => sum(k)[m.key] !== undefined));
  return (
    <div id="compareTable" className="tablewrap">
      <table className="data">
        <thead><tr><th>Measure</th>{ALGO_KEYS.map((k) => <th key={k}>{ALGO_NAME[k]}</th>)}</tr></thead>
        <tbody>
          {metrics.map((m) => {
            const vals = ALGO_KEYS.map((k) => sum(k)[m.key]);
            const nums = vals.filter((v): v is number => typeof v === "number");
            const target = m.best === "max" ? Math.max(...nums) : m.best === "min" ? Math.min(...nums) : null;
            const allSame = nums.every((v) => Math.abs(v - nums[0]) < 1e-9);
            return (
              <tr key={m.key}><td>{m.label}</td>
                {vals.map((v, i) => <td key={i} className={target !== null && !allSame && v === target ? "best" : undefined}>{v === undefined ? "–" : m.f(v)}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="hint">Highlighted cell = best value in that row. Vehicles used and pools formed describe how a plan is built, not how good it is, so they{"’"}re never highlighted.</p>
      {hasFg && (
        <p className="hint"><b>Assumptions, not data.</b> Produce a plan does not haul is valued at the farm-gate price, taken as {disc !== undefined ? fmt(disc * 100, 0) + "%" : "a fixed share"} below the median mandi price. ILO and both baselines are costed the same way (the empty return leg is paid and spoilage counts from pickup), so the comparison is like-for-like. Individual Transport and Proximity Pooling model farmers who haul by simple rules{beh ? ` (mandi within ${fmt(beh.max_haul_km, 0)} km and at least ${fmt(beh.price_margin * 100, 0)}% above the trader’s offer)` : ""}, hire spot trucks{beh ? ` at a ${fmt((beh.spot_markup - 1) * 100, 0)}% markup with a ${fmt(beh.spot_lead_hr, 1)} h wait` : ""}, and do not calculate profit, so some of their trips lose money.</p>
      )}
    </div>
  );
}

export function CompareView({ go }: { go: (v: ViewName) => void }) {
  const { state, actions } = useApp();
  const computing = state.planStatus === "computing";
  const head = (
    <PageHead title="ILO vs the baselines" lede="Read return and produce sold together. A high return with low coverage means most of the harvest never got paid for."
      action={<BusyButton busy={computing} busyLabel={"Computing…"} label="Run comparison" onClick={() => void actions.computePlan()} />} />
  );
  if (!state.plan) return <>{head}<NoPlan title="Nothing to compare yet" text="Run the comparison to see all three approaches side by side on the current data." go={go} /></>;
  return (
    <>
      {head}
      <StaleBanner busy={computing} onRecompute={() => void actions.computePlan()} />
      <div id="compareBody">
        <Scoreboard plan={state.plan} />
        <div className="sec"><div className="sec-head"><h2>Full breakdown</h2></div><Breakdown plan={state.plan} /></div>
      </div>
    </>
  );
}
