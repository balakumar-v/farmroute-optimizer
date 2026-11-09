import { useEffect, useState } from "react";
import type { FleetUsage } from "../lib/api";
import { fmt } from "../lib/format";
import { useApp } from "../state/store";

/** What "vehicles used" hides: dispatched vs idle, how full trips were, hired trucks, and why pools got no truck. */
export function FleetUsagePanel({ planId }: { planId: number }) {
  const { actions } = useApp();
  const api = actions.api;
  const [u, setU] = useState<FleetUsage | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    setU(null); setErr("");
    api.fleetUsage(planId).then((r) => { if (live) setU(r); }).catch((e) => { if (live) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [api, planId]);
  if (err) return <div className="note warn" role="note"><span>Fleet usage unavailable: {err}</span></div>;
  if (!u) return null;
  return (
    <div className="sec">
      <div className="sec-head"><h2>Fleet usage</h2><span className="grow" /></div>
      <div className="statement">
        <div>
          <h2>Overall</h2>
          <dl>
            <div className="line"><dt>Own vehicles dispatched</dt><dd>{u.dispatched} of {u.fleet_size} ({fmt(u.dispatched_pct, 0)}%)</dd></div>
            <div className="line sub"><dt>Idle</dt><dd>{u.idle}</dd></div>
            <div className="line"><dt>Trips run</dt><dd>{u.trips}{u.spot_trips ? ` (${u.spot_trips} on hired trucks)` : ""}</dd></div>
            <div className="line"><dt>Average load</dt><dd>{fmt(u.avg_load_pct, 0)}% of capacity</dd></div>
          </dl>
        </div>
        <div>
          <h2>By vehicle type</h2>
          <dl>
            {u.by_type.map((r) => (
              <div className="line" key={r.class}><dt>{r.class} ({r.dispatched}/{r.owned} used)</dt><dd>{r.trips} trips, {r.avg_load_pct == null ? "-" : `${fmt(r.avg_load_pct, 0)}% full`}</dd></div>
            ))}
          </dl>
        </div>
      </div>
      {u.unserved.length > 0 && (
        <div className="note warn" role="note"><span>
          {u.unserved.length} pool{u.unserved.length === 1 ? "" : "s"} ({fmt(u.unserved_kg, 0)} kg) got no truck:{" "}
          {u.unserved.map((x) => `pool ${x.pool + 1}: ${x.reason}`).join("; ")}.
        </span></div>
      )}
    </div>
  );
}
