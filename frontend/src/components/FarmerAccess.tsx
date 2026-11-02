import { useEffect, useState } from "react";
import type { PublishResult } from "../lib/api";
import { useApp } from "../state/store";
import { BusyButton } from "./Shell";

type Pins = { farmer_id: number; pin: string }[];

/** Operator tools for the farmer app: hand out PINs, choose which plan farmers see. */
export function FarmerAccess() {
  const { state, actions } = useApp();
  const api = actions.api;
  const planId = state.plan?.id;
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [pins, setPins] = useState<Pins | null>(null);
  const [pub, setPub] = useState<PublishResult | null>(null);
  const [live, setLive] = useState<{ published: boolean; plan_id?: number; published_at?: string } | null>(null);

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name); setErr("");
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  };
  const refresh = () => run("status", async () => setLive(await api.published()));
  useEffect(() => { void refresh(); }, [state.apiBase]);   // eslint-disable-line react-hooks/exhaustive-deps

  const issue = (onlyMissing: boolean) => {
    if (!onlyMissing && !window.confirm("This gives EVERY farmer a new PIN and logs them all out. Continue?")) return;
    void run("pins", async () => setPins((await api.issuePins(onlyMissing)).pins));
  };
  const text = () => (pins ?? []).map((p) => `${p.farmer_id}\t${p.pin}`).join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob(["farmer_id,pin\n" + (pins ?? []).map((p) => `${p.farmer_id},${p.pin}`).join("\n")], { type: "text/csv" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "farmer-pins.csv" });
    a.click(); URL.revokeObjectURL(url);
  };

  return (
    <div className="sec" id="farmerAccess">
      <div className="sec-head"><h2>Farmer access</h2></div>
      <p className="hint">
        {live === null ? "Checking…" : live.published
          ? <>Farmers currently see <strong>plan {live.plan_id}</strong>, published {live.published_at ? new Date(live.published_at).toLocaleString() : ""}.</>
          : "No plan is published: farmers see \u201cyour plan is not ready\u201d."}
      </p>
      {err && <div className="note warn" role="alert"><span>{err}</span></div>}
      <div className="head-actions" style={{ flexWrap: "wrap", gap: 8 }}>
        <BusyButton busy={busy === "pins"} busyLabel="Issuing…" label="Issue PINs (farmers without one)" className="btn btn-secondary" onClick={() => issue(true)} />
        <button className="btn btn-secondary" type="button" disabled={busy !== ""} onClick={() => issue(false)}>Re-issue for everyone</button>
        <BusyButton busy={busy === "publish"} busyLabel="Publishing…" label={planId ? `Publish plan ${planId} to farmers` : "Publish plan to farmers"} disabled={!planId}
          onClick={() => void run("publish", async () => { setPub(await api.publish(planId!)); setLive(await api.published()); })} />
        {live?.published && <button className="btn btn-secondary" type="button" disabled={busy !== ""}
          onClick={() => void run("unpublish", async () => { await api.unpublish(); setPub(null); setLive(await api.published()); })}>Hide from farmers</button>}
      </div>

      {pub && (
        <div className="note" role="status"><span>
          Published plan {pub.plan_id} to {pub.farmers} farmers. {pub.farmers_with_changes > 0 && `${pub.farmers_with_changes} will see a "something changed" banner. `}
          {pub.farmers_without_pin.length > 0
            ? <strong>{pub.farmers_without_pin.length} farmers have no PIN yet and cannot log in (IDs: {pub.farmers_without_pin.join(", ")}).</strong>
            : "Every farmer has a PIN."}
        </span></div>
      )}

      {pins && (
        <div>
          <div className="note warn" role="alert"><span>
            {pins.length === 0 ? "Every farmer already has a PIN." : `${pins.length} PINs issued. They are shown only now and are stored only as hashes: copy or download them before leaving this page.`}
          </span></div>
          {pins.length > 0 && <>
            <div className="head-actions" style={{ margin: "8px 0" }}>
              <button className="btn btn-secondary" type="button" onClick={() => void navigator.clipboard.writeText(text())}>Copy all</button>
              <button className="btn btn-secondary" type="button" onClick={download}>Download CSV</button>
              <button className="btn btn-secondary" type="button" onClick={() => setPins(null)}>Hide</button>
            </div>
            <div className="tablewrap"><table className="data"><thead><tr><th>Farmer ID</th><th>PIN</th></tr></thead>
              <tbody>{pins.map((p) => <tr key={p.farmer_id}><td>{p.farmer_id}</td><td style={{ fontVariantNumeric: "tabular-nums", letterSpacing: ".08em" }}>{p.pin}</td></tr>)}</tbody></table></div>
          </>}
        </div>
      )}
    </div>
  );
}
