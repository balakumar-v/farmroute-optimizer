import { useMemo, useState, type ReactNode } from "react";
import { Icon } from "../components/Icon";
import { BusyButton, PageHead, StaleBanner } from "../components/Shell";
import { fmt, inr } from "../lib/format";
import type { PlanMode, Pool, ViewName } from "../lib/types";
import { useApp } from "../state/store";

export function Line({ label, value, cls }: { label: ReactNode; value: ReactNode; cls?: string }) {
  return <div className={"line " + (cls ?? "")}><dt>{label}</dt><dd>{value}</dd></div>;
}

/** Shared empty / error state for Plan and Compare. */
export function NoPlan({ title, text, go }: { title: string; text: string; go: (v: ViewName) => void }) {
  const { state, actions } = useApp();
  const hasData = state.farmers.length > 0 && state.vehicles.length > 0 && state.markets.length > 0;
  if (state.planStatus === "error") {
    return <div className="empty"><h2 className="bad-text">Couldn{"’"}t compute a plan</h2><p>{state.planError}</p></div>;
  }
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{text}</p>
      <div className="empty-actions">
        {hasData && <BusyButton busy={state.planStatus === "computing"} busyLabel={"Computing…"} label="Compute from current data" onClick={() => void actions.computePlan()} />}
        <button className="btn btn-secondary" type="button" onClick={() => go("start")}>Go to scenarios<Icon name="arrow" /></button>
      </div>
    </div>
  );
}

type SortKey = "idx" | "net" | "load" | "unsold";

function poolVehicle(p: Pool): ReactNode {
  if (p.sold_at_farmgate) return <span className="tag warn">Sold at the farm gate</span>;
  if (p.withheld) return <span className="tag warn">Withheld: unprofitable</span>;
  if (p.spot_hire) return "Hired truck";
  return <>Vehicle {p.vehicle_id}{p.infeasible && <> <span className="tag bad">Infeasible</span></>}</>;
}

function PoolsTable({ pools }: { pools: Pool[] }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "idx", desc: false });
  const rows = useMemo(() => {
    const withIdx = pools.map((p, i) => ({ p, i }));
    const val = (r: { p: Pool; i: number }) => sort.key === "idx" ? r.i : sort.key === "net" ? r.p.net_return ?? 0 : sort.key === "load" ? r.p.total_qty_kg ?? 0 : r.p.unsold_kg ?? 0;
    return withIdx.sort((a, b) => (val(a) - val(b)) * (sort.desc ? -1 : 1));
  }, [pools, sort]);
  if (!pools.length) return <p className="hint">No pools in this plan.</p>;
  const th = (label: string, num?: boolean, key?: SortKey) => (
    <th className={num ? "num" : undefined} aria-sort={key && sort.key === key ? (sort.desc ? "descending" : "ascending") : undefined}>
      {key ? <button className="th-sort" onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== "idx" }))}>{label}{sort.key === key ? (sort.desc ? " ▾" : " ▴") : ""}</button> : label}
    </th>
  );
  const bad = (v?: number) => (v && v > 0 ? "num bad-text" : "num");
  return (
    <table className="data ledger stack">
      <thead><tr>{th("Pool", false, "idx")}{th("Vehicle")}{th("Farmers", true)}{th("Load", true, "load")}{th("Revenue", true)}{th("Transport", true)}{th("Net return", true, "net")}{th("Spoiled", true)}{th("Unsold", true, "unsold")}{th("No truck", true)}{th("Markets")}</tr></thead>
      <tbody>
        {rows.map(({ p, i }) => (
          <tr key={i}>
            <td className="pool-id" data-label="Pool">{i + 1}</td>
            <td data-label="Vehicle">{poolVehicle(p)}</td>
            <td className="num" data-label="Farmers">{(p.farmer_ids ?? []).length}</td>
            <td className="num" data-label="Load">{fmt(p.total_qty_kg, 1)} kg</td>
            <td className="num" data-label="Revenue">{inr(p.revenue)}</td>
            <td className="num" data-label="Transport">{inr(p.transport_cost)}</td>
            <td className="num net" data-label="Net return">{inr(p.net_return)}</td>
            <td className="num" data-label="Spoiled">{fmt(p.spoilage_loss_kg, 1)} kg</td>
            <td className={bad(p.unsold_kg)} data-label="Unsold">{fmt(p.unsold_kg, 1)} kg</td>
            <td className={bad(p.unserved_no_vehicle_kg)} data-label="No truck">{fmt(p.unserved_no_vehicle_kg, 1)} kg</td>
            <td data-label="Markets">{(p.markets_used ?? []).length ? (p.markets_used ?? []).map((m) => <span key={m} className="tag">Market {m} </span>) : "–"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PlanView({ go }: { go: (v: ViewName) => void }) {
  const { state, actions } = useApp();
  const computing = state.planStatus === "computing";
  const plan = state.plan;
  const head = (
    <PageHead title="Recommended plan" lede="Integrated Logistics Optimization (ILO), computed fresh from the data on the Data tab."
      action={
        <div className="head-actions">
          <label className="mode-pick"><span>Optimise for</span>
            <select value={state.planMode} disabled={computing} onChange={(e) => actions.setPlanMode(e.target.value as PlanMode)}>
              <option value="returns">Net return</option>
              <option value="spoilage">Least spoilage</option>
            </select>
          </label>
          <BusyButton busy={computing} busyLabel={"Computing…"} label="Compute plan" onClick={() => void actions.computePlan()} />
        </div>} />
  );
  if (!plan) return <>{head}<NoPlan title="No plan yet" text="Run a scenario from the Scenarios tab, or compute one from the data you entered." go={go} /></>;

  const ilo = plan.integrated_logistics_optimization;
  const s = ilo.summary ?? {};
  const total = s.total_qty_kg || 0;
  const pctOf = (kg?: number) => (total > 0 ? Math.max(0, ((kg || 0) / total) * 100) : 0);
  const unsold = s.total_unsold_kg || 0, noTruck = s.total_unserved_no_vehicle_kg || 0, withheld = s.total_withheld_kg || 0;
  const hasFg = s.farmgate_revenue !== undefined;
  const chosen = plan.realistic_baselines?.ilo_meta?.chosen;
  const fellBack = !!(chosen && chosen.startsWith("fallback:"));
  const missed = unsold + noTruck + withheld;
  const soldPct = Math.max(0, 100 - pctOf(missed));
  // Revenue - transport = net holds for this algorithm; only draw it as arithmetic when it does.
  const adds = s.total_revenue !== undefined && s.total_transport_cost !== undefined && Math.abs(s.total_revenue - s.total_transport_cost - (s.net_return ?? 0)) < 1;

  const coverageText = missed > 0.05
    ? hasFg
      ? `${fmt(100 - soldPct, 1)}% of the harvest (${fmt(missed, 1)} kg) was not sold at a market. Produce the plan did not haul is valued at the assumed farm-gate price (${fmt((s.farmgate_discount || 0) * 100, 0)}% below the median mandi price), which is an assumption, not data. Read net return and coverage together.`
      : `${fmt(100 - soldPct, 1)}% of the harvest (${fmt(missed, 1)} kg) never reached a paying market. A high net return with low coverage means the plan is leaving produce behind, so read the two together.`
    : "";
  const fallbackText = fellBack && chosen
    ? `ILO found no set of trips that beats a simpler plan under these prices, so it recommends that plan instead (${chosen.replace("fallback:", "").replace(/_/g, " ")}). On this scenario the pooling logic adds nothing; try a lower farm-gate price or nearer mandis.`
    : "";
  const pools = ilo.pools ?? [];
  const meta = plan.realistic_baselines?.ilo_meta;
  const sf = meta?.mode === "spoilage" ? meta.spoilage_first : undefined;
  const picked = sf?.frontier.find((x) => x.weight === sf.chosen_weight);
  const spoilText = sf && picked && sf.returns_plan_value > 0
    ? `Spoilage-first plan: ${fmt(picked.spoilage_kg, 1)} kg spoiled in transit, against ${fmt(sf.returns_plan_spoilage_kg, 1)} kg for the net-return plan. Farmer value is ${fmt((picked.value / sf.returns_plan_value) * 100, 1)}% of the net-return plan (allowed to fall by up to ${fmt(sf.max_value_sacrifice * 100, 0)}%). It hauls ${fmt(picked.hauled_kg, 0)} kg, so more produce may be sold at the farm gate.`
    : "";

  return (
    <>
      {head}
      <StaleBanner busy={computing} onRecompute={() => void actions.computePlan()} />
      {state.planStatus === "error" && <div className="note warn" role="alert"><Icon name="alert" small={false} /><span>{state.planError}</span></div>}
      <div id="planBody">
        <div id="dashSummary" className="statement">
          <div>
            <h2>Return</h2>
            <dl>
              <Line label="Revenue" value={inr(s.total_revenue)} />
              <Line label={adds ? "Less transport cost" : "Transport cost"} value={(adds ? "−" : "") + inr(s.total_transport_cost)} />
              <Line label="Net return" value={inr(s.net_return)} cls="total" />
              <Line label="Per farmer" value={inr(s.net_return_per_farmer)} cls="sub" />
              {hasFg && <>
                <Line label="Produce not hauled, at the assumed farm-gate price" value={inr(s.farmgate_revenue)} cls="sub" />
                <Line label="Farmer value (net return + farm gate)" value={inr(s.net_return_incl_farmgate)} cls="total" />
              </>}
            </dl>
          </div>
          <div>
            <h2>Harvest</h2>
            <dl><Line label="Harvest collected" value={`${fmt(total, 1)} kg`} /><Line label="Sold at a market" value={`${fmt(soldPct, 1)}%`} /></dl>
            <div className="harvest-bar" role="img" aria-label={`${fmt(soldPct, 1)}% of the harvest sold`}>
              <i className="seg-sold" style={{ width: `${soldPct}%` }} />
              {unsold > 0 && <i className="seg-unsold" style={{ width: `${pctOf(unsold)}%` }} />}
              {noTruck > 0 && <i className="seg-notruck" style={{ width: `${pctOf(noTruck)}%` }} />}
              {withheld > 0 && <i className="seg-withheld" style={{ width: `${pctOf(withheld)}%` }} />}
            </div>
            <dl>
              {unsold > 0 && <Line label={<><span className="key unsold" />Unsold at market</>} value={`${fmt(unsold, 1)} kg`} />}
              {noTruck > 0 && <Line label={<><span className="key notruck" />Never got a truck</>} value={<span className="bad-text">{fmt(noTruck, 1)} kg</span>} />}
              {withheld > 0 && <Line label={<><span className="key withheld" />{hasFg ? "Not hauled: sold at the farm gate" : "Withheld as unprofitable"}</>} value={`${fmt(withheld, 1)} kg`} />}
              <Line label="Spoilage in transit" value={`${fmt(s.total_spoilage_kg, 1)} kg`} cls="sub" />
              <Line label="Pools formed" value={fmt(s.pools_formed)} cls="sub" />
              <Line label="Vehicles used" value={fmt(s.vehicles_used) + (s.vehicle_utilization_pct !== undefined ? ` (${fmt(s.vehicle_utilization_pct, 0)}% utilised)` : "")} cls="sub" />
            </dl>
          </div>
        </div>

        {spoilText && (
          <div id="dashSpoilNote" className="note" role="note"><Icon name="check" small={false} /><span>{spoilText}</span></div>
        )}

        {(missed > 0.05 || fellBack) && (
          <div id="dashCoverageNote" className="note warn" role="note"><Icon name="alert" small={false} /><span>{[fallbackText, coverageText].filter(Boolean).join(" ")}</span></div>
        )}

        <div className="sec">
          <div className="sec-head"><h2>Pools</h2><span className="count">{pools.length}</span><span className="grow" />
            <button className="btn btn-secondary" type="button" onClick={() => go("map")}><Icon name="map" />See them on the map</button></div>
          <div className="tablewrap"><PoolsTable pools={pools} /></div>
        </div>

        <p className="sensor-strip"><strong>Live sensors:</strong> ESP32 readings are received by the backend, but the planner can{"’"}t recompute from them yet. Nothing is simulated here.</p>
      </div>
    </>
  );
}
