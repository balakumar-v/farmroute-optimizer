import { useEffect, useState } from "react";
import type { Fairness } from "../lib/api";
import { fmt, inr } from "../lib/format";
import { useApp } from "../state/store";

/** Who gains from the plan, and how evenly. Gain = payout minus the assumed doorstep value. */
export function FairnessPanel({ planId }: { planId: number }) {
  const { actions } = useApp();
  const api = actions.api;
  const [f, setF] = useState<Fairness | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    setF(null); setErr("");
    api.fairness(planId).then((r) => { if (live) setF(r); }).catch((e) => { if (live) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [api, planId]);
  if (err) return <div className="note warn" role="note"><span>Fairness report unavailable: {err}</span></div>;
  if (!f) return null;
  const [p10, med, p90] = f.gain_per_kg_p10_median_p90;
  const none = f.by_status.farmgate + f.by_status.unserved;
  return (
    <div className="sec">
      <div className="sec-head"><h2>Fairness</h2><span className="grow" /></div>
      <div className="statement">
        <div>
          <h2>Who gains</h2>
          <dl>
            <div className="line"><dt>Farmers who gain</dt><dd>{f.gaining} of {f.farmers} ({fmt(f.share_gaining * 100, 0)}%)</dd></div>
            <div className="line sub"><dt>Not hauled (sell at the doorstep)</dt><dd>{f.by_status.farmgate}</dd></div>
            <div className="line sub"><dt>Wanted a truck, none free</dt><dd className={f.by_status.unserved ? "bad-text" : ""}>{f.by_status.unserved}</dd></div>
            <div className="line"><dt>Total gain over doorstep prices</dt><dd>{inr(f.total_gain_inr)}</dd></div>
          </dl>
        </div>
        <div>
          <h2>How evenly</h2>
          <dl>
            <div className="line"><dt>Gain per hauled farmer</dt><dd>{inr(f.gain_per_hauled_farmer_inr)} (min {inr(f.min_hauled_gain_inr)}, max {inr(f.max_hauled_gain_inr)})</dd></div>
            <div className="line"><dt>Gain per kg: low / median / high</dt><dd>{[p10, med, p90].map((x) => (x == null ? "-" : inr(x, 2))).join(" / ")}</dd></div>
            <div className="line"><dt>Gini of gains (0 = equal)</dt><dd>{fmt(f.gini_of_gains, 2)}</dd></div>
            <div className="line"><dt>Share of the gain going to the bottom fifth</dt><dd>{fmt(f.bottom_fifth_share_of_gain * 100, 1)}%</dd></div>
          </dl>
        </div>
      </div>
      <div className="note" role="note"><span>{none > 0 ? `${none} farmer${none === 1 ? "" : "s"} gain nothing by construction (not hauled). ` : ""}Gains rest on the assumed doorstep price. Split rule: {f.split_rules.join(", ") || "n/a"}.</span></div>
    </div>
  );
}
