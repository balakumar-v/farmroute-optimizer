import { useEffect, useState } from "react";
import type { PhoneSummary, PinStatus, PublishResult } from "../lib/api";
import { useApp } from "../state/store";
import { BusyButton } from "./Shell";
import { buildPrintHtml, openPrintWindow, parseIds, writePrintWindow, type PerPage } from "../lib/printCards";
import { PRINT_LANGS, type PrintLang } from "../lib/printStrings";

type Pins = { farmer_id: number; pin: string }[];

/** Operator tools for the farmer app: hand out PINs, choose which plan farmers see. */
export function FarmerAccess() {
  const { state, actions } = useApp();
  const api = actions.api;
  const planId = state.plan?.id;
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [pins, setPins] = useState<Pins | null>(null);
  const [pinList, setPinList] = useState<PinStatus | null>(null);
  const [pub, setPub] = useState<PublishResult | null>(null);
  const [pLang, setPLang] = useState<PrintLang>("en");
  const [pPer, setPPer] = useState<PerPage>(4);
  const [pIds, setPIds] = useState("");
  const [live, setLive] = useState<{ published: boolean; plan_id?: number; published_at?: string } | null>(null);
  const [ph, setPh] = useState<PhoneSummary | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [cleared, setCleared] = useState<number | null>(null);

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name); setErr("");
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  };
  const refresh = () => run("status", async () => setLive(await api.published()));
  const loadPhones = () => run("phones", async () => setPh(await api.phones()));
  useEffect(() => { void refresh(); void loadPhones(); }, [state.apiBase]);   // eslint-disable-line react-hooks/exhaustive-deps
  // Wipes every stored number. Farmers are asked for theirs again next time they open the app.
  const resetPhones = () => run("resetPhones", async () => {
    const r = await api.resetPhones();
    setCleared(r.cleared); setConfirmText(""); setPh(await api.phones());
  });

  const issue = (onlyMissing: boolean) => {
    if (!onlyMissing && !window.confirm("This gives EVERY farmer a new PIN and logs them all out. Continue?")) return;
    void run("pins", async () => setPins((await api.issuePins(onlyMissing)).pins));
  };
  // Printable cards for farmers without a phone: opens a print view; "Save as PDF" in the print dialog gives the PDF.
  const printCards = () => {
    let ids: Set<number> | null;
    try { ids = parseIds(pIds); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); return; }
    const w = openPrintWindow();   // must open inside the click, before any await, or pop-up blockers stop it
    if (!w) { setErr("The browser blocked the print window. Allow pop-ups for this site and try again."); return; }
    void run("print", async () => {
      try {
        const data = await api.publishedCards();
        const { html, count } = buildPrintHtml(data, pLang, pPer, ids);
        if (count === 0) { w.close(); throw new Error("No published card matches those farmer IDs."); }
        writePrintWindow(w, html);
      } catch (e) { w.close(); throw e; }
    });
  };
  const showPins = () => run("pinList", async () => setPinList(await api.pinStatus()));
  // One farmer's PIN is replaced and shown once (the old one stops working and that farmer is logged out).
  const reissueOne = (id: number) => {
    if (!window.confirm(`Give farmer ${id} a new PIN? The old one stops working and they are logged out.`)) return;
    void run("pinOne", async () => {
      const r = await api.issuePin(id);
      setPins([{ farmer_id: r.farmer_id, pin: r.pin }]);
      setPinList(await api.pinStatus());
    });
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
        <BusyButton busy={busy === "pinList"} busyLabel="Loading…" label="View current PINs" className="btn btn-secondary" disabled={busy !== "" && busy !== "pinList"} onClick={() => void showPins()} />
        <BusyButton busy={busy === "publish"} busyLabel="Publishing…" label={planId ? `Publish plan ${planId} to farmers` : "Publish plan to farmers"} disabled={!planId}
          onClick={() => void run("publish", async () => { setPub(await api.publish(planId!)); setLive(await api.published()); setTimeout(() => void api.phones().then(setPh).catch(() => undefined), 3000); })} />
        {live?.published && <button className="btn btn-secondary" type="button" disabled={busy !== ""}
          onClick={() => void run("unpublish", async () => { await api.unpublish(); setPub(null); setLive(await api.published()); })}>Hide from farmers</button>}
      </div>

      <div className="sec-head" style={{ marginTop: 16 }}><h3>Printed cards (farmers without a phone)</h3></div>
      <p className="hint">Makes one card per farmer from the published plan, in the language you pick. Cards contain no PIN. Reprint if you publish a new plan.</p>
      <div className="head-actions" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
        <label>Language<select value={pLang} onChange={(e) => setPLang(e.target.value as PrintLang)}>
          {PRINT_LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}</select></label>
        <label>Cards per page<select value={pPer} onChange={(e) => setPPer(Number(e.target.value) as PerPage)}>
          <option value={4}>4 (A6 size, cut lines)</option><option value={1}>1 (large print)</option></select></label>
        <label>Farmer IDs (blank = all)<input value={pIds} onChange={(e) => setPIds(e.target.value)} placeholder="e.g. 3, 8-12, 20" /></label>
        <BusyButton busy={busy === "print"} busyLabel="Preparing…" label="Print / Save as PDF" className="btn btn-secondary"
          disabled={!live?.published || (busy !== "" && busy !== "print")} onClick={printCards} />
      </div>


      <div className="sec-head" style={{ marginTop: 16 }}><h3>Phone numbers (SMS and WhatsApp updates)</h3></div>
      <p className="hint">
        Farmers add their own number in the farmer app and confirm it with a code sent by SMS. When you publish a plan, farmers with a
        number whose plan changed get an SMS and a WhatsApp message (everyone with a number on the first publish). Numbers are shown masked.
      </p>
      {ph && (["sms", "whatsapp"] as const).map((ch) => ph.providers[ch].problem
        ? <div className="note warn" role="alert" key={ch}><span><strong>{ch === "sms" ? "SMS" : "WhatsApp"}:</strong> {ph.providers[ch].provider} {ph.providers[ch].problem}. Messages will fail until this is fixed.</span></div> : null)}
      {ph && !ph.providers.sms.live && !ph.providers.whatsapp.live && !ph.providers.sms.problem && !ph.providers.whatsapp.problem && (
        <div className="note" role="status"><span>Dry-run mode: messages are written to the server log, not sent. Set <code>SMS_PROVIDER</code> and <code>WHATSAPP_PROVIDER</code> on the backend to send for real.</span></div>
      )}
      <p className="hint">
        {ph === null ? "Checking…" : <><strong>{ph.registered}</strong> of {ph.farmers} farmers have a number.
          {cleared !== null && ` Last reset cleared ${cleared}.`}</>}
      </p>
      <div className="head-actions" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
        <label>Type RESET to clear every number
          <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder="RESET" autoComplete="off" /></label>
        <BusyButton busy={busy === "resetPhones"} busyLabel="Clearing…" label="Reset all phone numbers" className="btn btn-secondary"
          disabled={confirmText.trim() !== "RESET" || !ph || ph.registered === 0 || (busy !== "" && busy !== "resetPhones")} onClick={resetPhones} />
        <button className="btn btn-secondary" type="button" disabled={busy !== ""} onClick={() => void loadPhones()}>Refresh</button>
      </div>
      <p className="hint">Resetting deletes all stored numbers. Farmers will be asked for their number again the next time they open the app, and get no messages until they confirm it.</p>

      {ph && ph.rows.length > 0 && (
        <div className="tablewrap" style={{ maxHeight: 260, overflow: "auto" }}><table className="data"><thead><tr><th>Farmer ID</th><th>Number</th><th>Language</th><th>Confirmed</th><th /></tr></thead>
          <tbody>{ph.rows.map((r) => <tr key={r.farmer_id}><td>{r.farmer_id}</td><td style={{ fontVariantNumeric: "tabular-nums" }}>{r.masked}</td><td>{r.lang}</td>
            <td>{new Date(r.verified_at * 1000).toLocaleString()}</td>
            <td><button className="btn btn-secondary" type="button" disabled={busy !== ""}
              onClick={() => void run("clearOne", async () => { await api.clearPhone(r.farmer_id); setPh(await api.phones()); })}>Clear</button></td></tr>)}</tbody></table></div>
      )}
      {ph && ph.recent.length > 0 && (<>
        <div className="sec-head" style={{ marginTop: 12 }}><h3>Recent messages (SMS & WhatsApp notifications)</h3></div>
        <div className="tablewrap" style={{ maxHeight: 240, overflow: "auto" }}>
          <table className="data">
            <thead>
              <tr>
                <th>Time</th>
                <th>Farmer</th>
                <th>Number</th>
                <th>Channel</th>
                <th>Provider</th>
                <th>Kind</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {ph.recent.map((m, i) => (
                <tr key={i}>
                  <td>{new Date(m.created_at * 1000).toLocaleTimeString()}</td>
                  <td>Farmer {m.farmer_id}</td>
                  <td style={{ fontVariantNumeric: "tabular-nums" }}>{m.masked || "-"}</td>
                  <td>
                    <span style={{
                      display: "inline-block",
                      padding: "2px 6px",
                      borderRadius: 4,
                      fontSize: "0.85em",
                      fontWeight: 600,
                      backgroundColor: m.channel === "whatsapp" ? "#e8f5e9" : "#e3f2fd",
                      color: m.channel === "whatsapp" ? "#1b5e20" : "#0d47a1"
                    }}>
                      {m.channel === "whatsapp" ? "WhatsApp" : "SMS"}
                    </span>
                  </td>
                  <td><code>{m.provider || m.channel}</code></td>
                  <td>{m.kind}</td>
                  <td>
                    {m.ok ? (
                      <span style={{ color: "#2e7d32" }}>✓ {m.detail}</span>
                    ) : (
                      <span style={{ color: "#c62828" }}>✗ <strong>{m.detail}</strong></span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>)}

      {pub && (
        <div className="note" role="status"><span>
          Published plan {pub.plan_id} to {pub.farmers} farmers. {pub.farmers_with_changes > 0 && `${pub.farmers_with_changes} will see a "something changed" banner. `}
          {pub.farmers_without_pin.length > 0
            ? <strong>{pub.farmers_without_pin.length} farmers have no PIN yet and cannot log in (IDs: {pub.farmers_without_pin.join(", ")}).</strong>
            : "Every farmer has a PIN."}
          {pub.phone_updates && (pub.phone_updates.farmers_messaged > 0
            ? ` ${pub.phone_updates.farmers_messaged} farmer${pub.phone_updates.farmers_messaged === 1 ? "" : "s"} with a phone number ${pub.phone_updates.dry_run ? "would get" : "are getting"} an SMS and a WhatsApp update${pub.phone_updates.dry_run ? " (dry run: logged, nothing sent)" : ""}.`
            : " No SMS or WhatsApp updates to send: nobody with a number has a changed plan.")}
        </span></div>
      )}

      {pinList && (
        <div>
          <div className="note" role="status"><span>
            <strong>{pinList.with_pin}</strong> of {pinList.farmers} farmers have a PIN. PINs are stored only as salted hashes, so the digits cannot be shown again after they were issued: if a farmer lost theirs, re-issue it (the old one stops working).
          </span></div>
          <div className="head-actions" style={{ margin: "8px 0" }}>
            <button className="btn btn-secondary" type="button" disabled={busy !== ""} onClick={() => void showPins()}>Refresh</button>
            <button className="btn btn-secondary" type="button" onClick={() => setPinList(null)}>Hide list</button>
          </div>
          <div className="tablewrap" style={{ maxHeight: 280, overflow: "auto" }}><table className="data"><thead><tr><th>Farmer ID</th><th>PIN</th><th>Issued</th><th>Status</th><th /></tr></thead>
            <tbody>{pinList.rows.map((r) => <tr key={r.farmer_id}><td>{r.farmer_id}</td>
              <td style={{ letterSpacing: ".08em" }}>{r.has_pin ? "\u2022\u2022\u2022\u2022\u2022\u2022 (set)" : "Not issued"}</td>
              <td>{r.issued_at ? new Date(r.issued_at * 1000).toLocaleString() : "-"}</td>
              <td>{!r.has_pin ? "No PIN" : r.locked ? "Locked (too many wrong tries)" : "Active"}</td>
              <td><button className="btn btn-secondary" type="button" disabled={busy !== ""} onClick={() => reissueOne(r.farmer_id)}>{r.has_pin ? "Re-issue" : "Issue"}</button></td></tr>)}</tbody></table></div>
        </div>
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
