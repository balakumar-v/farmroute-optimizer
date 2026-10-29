import { useState, type FormEvent, type ReactNode } from "react";
import { Icon } from "../components/Icon";
import { PageHead, StaleBanner } from "../components/Shell";
import { CROPS, VEHICLE_TYPES } from "../lib/constants";
import { fmt, inr } from "../lib/format";
import { useApp } from "../state/store";

function Section({ title, count, adder, adderLabel, children }: { title: string; count: number; adder: ReactNode; adderLabel: string; children: ReactNode }) {
  return (
    <div className="sec">
      <div className="sec-head"><h2>{title}</h2><span className="count">{count}</span><span className="grow" />
        <details className="adder"><summary className="btn btn-secondary"><Icon name="plus" />{adderLabel}</summary>{adder}</details>
      </div>
      <div className="tablewrap">{children}</div>
    </div>
  );
}

function TableState({ cols, empty, kind }: { cols: number; empty: string; kind: "farmers" | "vehicles" | "markets" }) {
  const { state, actions } = useApp();
  if (state.tables === "idle" || (state.tables === "loading" && !state[kind].length)) {
    return <>{[0, 1, 2].map((i) => <tr key={i} className="skeleton-row" aria-hidden="true"><td colSpan={cols}><span className="skeleton" /></td></tr>)}</>;
  }
  if (state.tables === "error") {
    return <tr><td className="empty-row" colSpan={cols}>Couldn{"’"}t load {kind}. {state.tablesError} <button className="link-btn" onClick={() => actions.loadTables()}>Retry</button></td></tr>;
  }
  return <tr><td className="empty-row" colSpan={cols}>{empty}</td></tr>;
}

function FormError({ msg }: { msg: string }) {
  return msg ? <p className="form-err" role="alert">{msg}</p> : null;
}

function FarmerForm() {
  const { actions } = useApp();
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const d = new FormData(form);
    const lat = Number(d.get("lat")), lng = Number(d.get("lng"));
    const ready = Number(d.get("ready_hr")), deadline = Number(d.get("deadline_hr"));
    const qty = Number(d.get("qty_kg"));
    const refrig = d.get("needs_refrigeration");
    if (lat < -90 || lat > 90) return setErr("Latitude must be between -90 and 90.");
    if (lng < -180 || lng > 180) return setErr("Longitude must be between -180 and 180.");
    if (!(qty > 0)) return setErr("Quantity must be above 0 kg.");
    if (!(deadline > ready)) return setErr("The deadline must be later than the ready time.");
    setErr(""); setBusy(true);
    try {
      await actions.addFarmer({ lat, lng, crop: String(d.get("crop")), qty_kg: qty, ready_hr: ready, deadline_hr: deadline, needs_refrigeration: refrig === "" ? null : refrig === "true" });
      form.reset();
      actions.toast("ok", "Farmer added.");
    } catch (ex) { setErr(ex instanceof Error ? ex.message : String(ex)); } finally { setBusy(false); }
  }
  return (
    <form id="farmerForm" className="grid-form" onSubmit={submit} noValidate>
      <div><label htmlFor="f-lat">Latitude</label><input id="f-lat" name="lat" type="number" step="any" required /></div>
      <div><label htmlFor="f-lng">Longitude</label><input id="f-lng" name="lng" type="number" step="any" required /></div>
      <div><label htmlFor="f-crop">Crop</label>
        <select id="f-crop" name="crop" required defaultValue=""><option value="" disabled>Choose crop{"…"}</option>{CROPS.map((c) => <option key={c} value={c}>{c}</option>)}</select></div>
      <div><label htmlFor="f-qty">Quantity (kg)</label><input id="f-qty" name="qty_kg" type="number" min="0" step="0.1" required /></div>
      <div><label htmlFor="f-ready">Ready at (hr)</label><input id="f-ready" name="ready_hr" type="number" min="0" step="0.1" required /></div>
      <div><label htmlFor="f-dead">Deadline (hr)</label><input id="f-dead" name="deadline_hr" type="number" min="0" step="0.1" required /></div>
      <div><label htmlFor="f-cold">Needs refrigeration</label>
        <select id="f-cold" name="needs_refrigeration" defaultValue=""><option value="">Auto (from crop)</option><option value="true">Yes</option><option value="false">No</option></select></div>
      <div className="form-act"><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Adding…" : "Add farmer"}</button></div>
      <FormError msg={err} />
    </form>
  );
}

function VehicleForm() {
  const { actions } = useApp();
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const d = new FormData(form);
    const count = Number(d.get("count"));
    if (!(count >= 1)) return setErr("Count must be at least 1.");
    setErr(""); setBusy(true);
    try {
      await actions.addVehicles({ type_name: String(d.get("type_name")), count });
      form.reset();
      actions.toast("ok", `Added ${count} vehicle${count > 1 ? "s" : ""}.`);
    } catch (ex) { setErr(ex instanceof Error ? ex.message : String(ex)); } finally { setBusy(false); }
  }
  return (
    <form id="vehicleForm" className="grid-form" onSubmit={submit} noValidate>
      <div><label htmlFor="v-type">Type</label>
        <select id="v-type" name="type_name" required defaultValue="">
          <option value="" disabled>Choose type{"…"}</option>
          {VEHICLE_TYPES.map((t) => <option key={t.name} value={t.name}>{`${t.name} — ${t.capacity_kg}kg${t.refrigerated ? ", refrigerated" : ""}, ₹${t.fixed_cost}+₹${t.per_km_cost}/km`}</option>)}
        </select></div>
      <div><label htmlFor="v-count">Count</label><input id="v-count" name="count" type="number" min="1" step="1" defaultValue={1} required /></div>
      <div className="form-act"><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Adding…" : "Add vehicle(s)"}</button></div>
      <FormError msg={err} />
    </form>
  );
}

interface CropRow { id: number; crop: string; price: string; cap: string }
let rowSeq = 0;
const newRow = (): CropRow => ({ id: ++rowSeq, crop: CROPS[0], price: "", cap: "" });

/** A market can quote several crops at once, so entry is a repeatable (crop, price/kg, capacity kg) row. */
function MarketForm() {
  const { actions } = useApp();
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [rows, setRows] = useState<CropRow[]>(() => [newRow()]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const patchRow = (id: number, p: Partial<CropRow>) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...p } : r)));

  async function submit() {
    if (lat === "" || lng === "") return setErr("Enter the market’s latitude and longitude.");
    const price: Record<string, number> = {}, capacity_kg: Record<string, number> = {};
    for (const r of rows) {
      if (r.price === "" || r.cap === "") continue; // skip incomplete rows
      price[r.crop] = Number(r.price);
      capacity_kg[r.crop] = Number(r.cap);
    }
    if (!Object.keys(price).length) return setErr("Add at least one crop with a price and capacity.");
    setErr(""); setBusy(true);
    try {
      await actions.addMarket({ lat: Number(lat), lng: Number(lng), price, capacity_kg });
      setLat(""); setLng(""); setRows([newRow()]);
      actions.toast("ok", "Market added.");
    } catch (ex) { setErr(ex instanceof Error ? ex.message : String(ex)); } finally { setBusy(false); }
  }

  return (
    <div className="market-add">
      <form id="marketForm" className="grid-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <div><label htmlFor="m-lat">Latitude</label><input id="m-lat" name="lat" type="number" step="any" required value={lat} onChange={(e) => setLat(e.target.value)} /></div>
        <div><label htmlFor="m-lng">Longitude</label><input id="m-lng" name="lng" type="number" step="any" required value={lng} onChange={(e) => setLng(e.target.value)} /></div>
      </form>
      <p className="hint">A market can buy several crops at once, each at its own price and capacity for this cycle.</p>
      <div id="marketCropRows" className="market-crop-rows">
        {rows.map((r) => (
          <div className="market-crop-row" key={r.id}>
            <div><label>Crop</label><select className="mc-crop" value={r.crop} onChange={(e) => patchRow(r.id, { crop: e.target.value })}>{CROPS.map((c) => <option key={c} value={c}>{c}</option>)}</select></div>
            <div><label>Price (&#8377;/kg)</label><input className="mc-price" type="number" min="0" step="0.1" value={r.price} onChange={(e) => patchRow(r.id, { price: e.target.value })} /></div>
            <div><label>Capacity (kg)</label><input className="mc-capacity" type="number" min="0" step="0.1" value={r.cap} onChange={(e) => patchRow(r.id, { cap: e.target.value })} /></div>
            <button type="button" className="remove-row" title="Remove crop" aria-label="Remove crop" disabled={rows.length === 1} onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}><Icon name="close" /></button>
          </div>
        ))}
      </div>
      <div className="row">
        <button type="button" className="btn btn-secondary" onClick={() => setRows((rs) => [...rs, newRow()])}><Icon name="plus" />Add crop</button>
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void submit()}>{busy ? "Adding…" : "Add market"}</button>
      </div>
      <FormError msg={err} />
    </div>
  );
}

export function DataView() {
  const { state, actions } = useApp();
  const { farmers, vehicles, markets } = state;
  return (
    <>
      <PageHead title="Data" lede="What the optimizer sees: farmers, the vehicle fleet and markets. Add rows by hand; the planning clock is hours from the start of the day." />
      <StaleBanner busy={state.planStatus === "computing"} onRecompute={() => void actions.computePlan()} />

      <Section title="Farmers" count={farmers.length} adderLabel="Add farmer" adder={<FarmerForm />}>
        <table id="farmerTable" className="data"><thead><tr><th>ID</th><th>Lat</th><th>Lng</th><th>Crop</th><th className="num">Qty (kg)</th><th className="num">Ready &ndash; deadline (hr)</th><th>Cold</th></tr></thead>
          <tbody>
            {farmers.length ? farmers.map((f) => (
              <tr key={f.id}><td>{f.id}</td><td>{fmt(f.lat, 4)}</td><td>{fmt(f.lng, 4)}</td><td>{f.crop}</td>
                <td className="num">{fmt(f.qty_kg, 1)}</td><td className="num">{fmt(f.ready_hr, 1)} &ndash; {fmt(f.deadline_hr, 1)}</td>
                <td>{f.needs_refrigeration ? <span className="tag cold">Cold</span> : "–"}</td></tr>
            )) : <TableState kind="farmers" cols={7} empty="No farmers yet. Run a scenario, or use Add farmer." />}
          </tbody></table>
      </Section>

      <Section title="Vehicles" count={vehicles.length} adderLabel="Add vehicles" adder={<VehicleForm />}>
        <table id="vehicleTable" className="data"><thead><tr><th>ID</th><th>Type</th><th className="num">Capacity (kg)</th><th>Cold</th><th className="num">Fixed cost</th><th className="num">Cost / km</th></tr></thead>
          <tbody>
            {vehicles.length ? vehicles.map((v) => (
              <tr key={v.id}><td>{v.id}</td><td>{v.type_name}</td><td className="num">{fmt(v.capacity_kg, 1)}</td>
                <td>{v.refrigerated ? <span className="tag cold">Cold</span> : "–"}</td><td className="num">{inr(v.fixed_cost, 2)}</td><td className="num">{inr(v.per_km_cost, 2)}</td></tr>
            )) : <TableState kind="vehicles" cols={6} empty="No vehicles yet. Run a scenario, or use Add vehicles." />}
          </tbody></table>
      </Section>

      <Section title="Markets" count={markets.length} adderLabel="Add market" adder={<MarketForm />}>
        <table id="marketTable" className="data"><thead><tr><th>ID</th><th>Lat</th><th>Lng</th><th>Crops (price &#8377;/kg, capacity kg)</th></tr></thead>
          <tbody>
            {markets.length ? markets.map((m) => (
              <tr key={m.id}><td>{m.id}</td><td>{fmt(m.lat, 4)}</td><td>{fmt(m.lng, 4)}</td>
                <td style={{ whiteSpace: "normal" }}>{Object.keys(m.price).map((c) => `${c} (₹${fmt(m.price[c], 2)}, ${fmt(m.capacity_kg[c] ?? 0, 1)} kg)`).join(", ")}</td></tr>
            )) : <TableState kind="markets" cols={4} empty="No markets yet. Run a scenario, or use Add market." />}
          </tbody></table>
      </Section>
    </>
  );
}
