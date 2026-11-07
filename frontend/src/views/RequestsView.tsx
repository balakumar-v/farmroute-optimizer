import { useCallback, useEffect, useMemo, useState } from "react";
import { BusyButton, PageHead } from "../components/Shell";
import { Icon } from "../components/Icon";
import type { ChangeList, ChangePreview, ChangeReason, ChangeStatus } from "../lib/api";
import { previewRows, rawText, reasonLabel, REASONS, rupees, sameIds, STATUS_FILTERS, whenText } from "../lib/changeRequests";
import { useApp } from "../state/store";

/** Farmers ask (in the farmer app) for a different quantity or time; nothing changes until you approve here. */
export function RequestsView() {
  const { state, actions } = useApp();
  const api = actions.api;
  const [status, setStatus] = useState<ChangeStatus>("pending");
  const [list, setList] = useState<ChangeList | null>(null);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [preview, setPreview] = useState<{ p: ChangePreview; ids: number[] } | null>(null);
  const [reason, setReason] = useState<ChangeReason>("other");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name); setErr("");
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  };
  const load = useCallback(async () => {
    const l = await api.changeRequests(status);
    setList(l);
    const here = new Set(l.requests.map((r) => r.id));
    setSel((s) => new Set([...s].filter((id) => here.has(id))));
  }, [api, status]);
  const refresh = () => run("load", load);
  useEffect(() => { setPreview(null); setSel(new Set()); void refresh(); }, [status, state.apiBase]);   // eslint-disable-line react-hooks/exhaustive-deps

  const pending = status === "pending";
  const ids = useMemo(() => [...sel].sort((a, b) => a - b), [sel]);
  // Approve only what was previewed, and only while the published plan is still the one previewed against.
  const fresh = preview !== null && sameIds(preview.ids, ids) && list?.published_plan_id === preview.p.base_plan_id;
  const toggle = (id: number) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const all = list?.requests ?? [];

  const doPreview = () => run("preview", async () => {
    try { setPreview({ p: await api.previewChanges(ids), ids }); }
    catch (e) { setPreview(null); await load(); throw e; }
  });
  const doApprove = () => {
    if (!preview || !fresh) return;
    const n = ids.length, c = preview.p.collateral_count;
    const ask = `Approve ${n} request${n === 1 ? "" : "s"}, recompute and publish the plan?\n\n`
      + `${preview.p.diff.farmers_changed} farmers get a different plan${c ? `, ${c} of them did not ask` : ""}. Farmers whose plan changed are messaged.`;
    if (!window.confirm(ask)) return;
    void run("approve", async () => {
      try {
        const r = await api.approveChanges(ids, preview.p.base_plan_id);
        actions.toast("ok", `Approved ${r.approved.length}. Plan ${r.plan_id} is live; ${r.farmers_changed} farmers have a changed plan.`);
        setPreview(null); setSel(new Set());
        await actions.dataChanged();
      } catch (e) { setPreview(null); await load(); throw e; }
      await load();
    });
  };
  const doReject = () => run("reject", async () => {
    for (const id of ids) await api.rejectChange(id, reason);
    actions.toast("ok", `Rejected ${ids.length} request${ids.length === 1 ? "" : "s"}.`);
    setPreview(null); setSel(new Set());
    await load();
  });
  const toggleWindow = () => run("window", async () => { if (list) { await api.changeWindow(!list.window_open); await load(); } });

  return (
    <>
      <PageHead title="Farmer requests" lede="Farmers ask for a different quantity or time in the farmer app. Nothing changes until you approve." />
      <div className="sec">
        <p className="hint">
          {list === null ? "Checking…" : list.published_plan_id === null
            ? "No plan is published, so farmers cannot send requests yet."
            : <>Farmers see <strong>plan {list.published_plan_id}</strong>. Requests are <strong>{list.window_open ? "open" : "closed"}</strong>.</>}
        </p>
        {err && <div className="note warn" role="alert"><Icon name="alert" small={false} /><span>{err}</span></div>}
        <div className="head-actions" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
          <label>Show<select value={status} onChange={(e) => setStatus(e.target.value as ChangeStatus)}>
            {STATUS_FILTERS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>
          <button className="btn btn-secondary" type="button" disabled={busy !== ""} onClick={() => void refresh()}>Refresh</button>
          {list && <button className="btn btn-secondary" type="button" disabled={busy !== ""} onClick={toggleWindow}>
            {list.window_open ? "Close requests (dispatch started)" : "Open requests again"}</button>}
        </div>

        {list && all.length === 0 && <p className="hint">{pending ? "No requests are waiting." : "Nothing here."}</p>}
        {all.length > 0 && (
          <div className="tablewrap" style={{ marginTop: 12 }}>
            <table className="data">
              <thead><tr>{pending && <th><span className="sr-only">Select</span></th>}<th>Farmer</th><th>They wrote</th><th>It means</th><th>Asked</th>{!pending && <th>Result</th>}</tr></thead>
              <tbody>{all.map((r) => (
                <tr key={r.id}>
                  {pending && <td><input type="checkbox" aria-label={`Select request ${r.id}`} checked={sel.has(r.id)} onChange={() => toggle(r.id)} /></td>}
                  <td>{r.farmer_id}{r.crop ? <span className="hint"> · {r.crop}</span> : null}</td>
                  <td style={{ maxWidth: 260, overflowWrap: "anywhere" }}>{rawText(r)}</td>
                  <td>{r.changes.map((c) => <div key={c.field}>{c.label}: {c.from} {"→"} {c.to}</div>)}</td>
                  <td>{whenText(r.created_at)}</td>
                  {!pending && <td>{r.status === "rejected" ? `Rejected: ${reasonLabel(r.reason_code)}` : r.status === "approved" ? `Approved in plan ${r.applied_plan_id}` : r.status}</td>}
                </tr>))}
              </tbody>
            </table>
          </div>
        )}

        {pending && all.length > 0 && (
          <div className="head-actions" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end", marginTop: 12 }}>
            <button className="btn btn-secondary" type="button" onClick={() => setSel(new Set(all.map((r) => r.id)))}>Select all</button>
            <BusyButton busy={busy === "preview"} busyLabel="Computing…" label={`Preview ${ids.length || ""} selected`.replace("  ", " ")} className="btn btn-secondary"
              disabled={ids.length === 0 || (busy !== "" && busy !== "preview")} onClick={doPreview} />
            <BusyButton busy={busy === "approve"} busyLabel="Publishing…" label="Approve and publish" disabled={!fresh || (busy !== "" && busy !== "approve")} onClick={doApprove} />
            <label>Reject for<select value={reason} onChange={(e) => setReason(e.target.value as ChangeReason)}>
              {REASONS.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}</select></label>
            <BusyButton busy={busy === "reject"} busyLabel="Rejecting…" label="Reject selected" className="btn btn-secondary"
              disabled={ids.length === 0 || (busy !== "" && busy !== "reject")} onClick={doReject} />
          </div>
        )}
        {pending && ids.length > 0 && !fresh && <p className="hint">Preview the selection first: approving recomputes the plan for every farmer.</p>}

        {preview && (
          <div style={{ marginTop: 16 }}>
            <div className="sec-head"><h3>Preview: plan {preview.p.base_plan_id} with {preview.ids.length} request{preview.ids.length === 1 ? "" : "s"} applied</h3></div>
            {!fresh && <div className="note warn" role="status"><Icon name="alert" small={false} /><span>The selection or the published plan changed since this preview. Preview again before approving.</span></div>}
            <p className="hint">
              <strong>{preview.p.diff.farmers_changed}</strong> farmers would get a different plan
              {preview.p.collateral_count > 0 ? <>: {preview.p.diff.farmers_changed - preview.p.collateral_count} asked, <strong>{preview.p.collateral_count} did not ask</strong>.</> : "; all of them asked."}
              {" "}Farmers not listed are unchanged. Nothing is saved or sent until you approve.
            </p>
            {preview.p.collateral_count > 0 && <div className="note warn" role="status"><Icon name="alert" small={false} /><span>Approving also changes the plan, and messages, farmers who did not ask.</span></div>}
            {preview.p.diff.farmers_changed > 0 && (
              <div className="tablewrap"><table className="data">
                <thead><tr><th>Farmer</th><th>Asked</th><th>What changes</th><th>Payout</th></tr></thead>
                <tbody>{previewRows(preview.p.diff, preview.p.requested_farmer_ids).map((r) => (
                  <tr key={r.farmerId}><td>{r.farmerId}</td><td>{r.asked ? "Yes" : "No"}</td><td>{r.why.join("; ")}</td><td style={{ fontVariantNumeric: "tabular-nums" }}>{rupees(r.payoutChange)}</td></tr>))}
                </tbody></table></div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
