import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { VIEWS } from "../lib/constants";
import type { ViewName } from "../lib/types";
import { useApp } from "../state/store";
import { Icon } from "./Icon";

export function Header({ view, go }: { view: ViewName; go: (v: ViewName) => void }) {
  return (
    <header className="mast">
      <div className="mast-in">
        <a className="brand" href="#start" aria-label="Farmroute Optimizer, home" onClick={(e) => { e.preventDefault(); go("start"); }}>
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" fill="#f2b705" />
            <path d="M5 8l9 8-9 8M14 16h11" fill="none" stroke="#10151c" strokeWidth="2.6" strokeLinejoin="round" />
            <rect x="24" y="13" width="6" height="6" fill="#10151c" />
          </svg>
          <span className="brand-name">Farmroute<span className="brand-sub">Optimizer</span></span>
        </a>
        <nav className="tabs" id="tabs" aria-label="Sections">
          {VIEWS.map((v) => (
            <button key={v.id} className={"tab" + (view === v.id ? " active" : "")} aria-current={view === v.id ? "page" : undefined} onClick={() => go(v.id)}>
              <Icon name={v.icon} small={false} /><span>{v.label}</span>
            </button>
          ))}
        </nav>
        <ConnChip />
      </div>
    </header>
  );
}

function hostOf(url: string) {
  try { return new URL(url).host; } catch { return url || "Backend"; }
}

function ConnChip() {
  const { state, actions } = useApp();
  const [draft, setDraft] = useState(state.apiBase);
  const [status, setStatus] = useState("");
  const ref = useRef<HTMLDetailsElement>(null);
  const label = state.conn === "ok" ? "Connected" : state.conn === "bad" ? "Unreachable" : "Backend";
  const hasData = state.farmers.length + state.vehicles.length + state.markets.length > 0;

  // close the popover on outside click / Escape
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (ref.current?.open && !ref.current.contains(e.target as Node)) ref.current.open = false; };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && ref.current?.open) ref.current.open = false; };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    setStatus("Saved. Checking…");
    const ok = await actions.setApiBase(draft);
    setStatus(ok ? "Saved and reachable." : "Saved, but nothing answered at that address.");
  }

  return (
    <details className="conn" id="connPanel" ref={ref}>
      <summary id="connSummary" aria-label={`Backend ${label.toLowerCase()}: ${state.apiBase}`}>
        <span className="conn-dot" id="connDot" data-state={state.conn} />
        <span className="conn-text" id="connText">{label}<span className="conn-host"> {"·"} {hostOf(state.apiBase)}</span></span>
        <Icon name="chevron" />
      </summary>
      <form className="conn-pop" onSubmit={save}>
        <label htmlFor="apiBase">Backend API base URL</label>
        <div className="row">
          <input id="apiBase" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="http://localhost:8000" inputMode="url" autoCapitalize="off" spellCheck={false} />
          <button id="saveApi" className="btn btn-secondary" type="submit">Save</button>
        </div>
        <p className="hint" role="status">{status}</p>
        <p className="hint">{hasData ? `Loaded: ${state.farmers.length} farmers, ${state.vehicles.length} vehicles, ${state.markets.length} markets.` : "No data loaded on the backend."}</p>
      </form>
    </details>
  );
}

/** Explains an unreachable backend in plain words, with the command to start it and a retry. */
export function BackendBanner() {
  const { state, actions } = useApp();
  const [busy, setBusy] = useState(false);
  if (state.conn !== "bad") return null;
  return (
    <div className="banner" role="alert">
      <div className="banner-in">
        <Icon name="alert" small={false} />
        <div className="banner-text">
          <strong>Can{"’"}t reach the backend at {state.apiBase}.</strong>
          <span> Start it from the project folder, then retry:</span>
          <code>cd backend &amp;&amp; uvicorn main:app --port 8000</code>
        </div>
        <button className="btn btn-secondary" disabled={busy} onClick={async () => { setBusy(true); await actions.loadTables(); setBusy(false); }}>
          {busy ? "Checking…" : "Retry"}
        </button>
      </div>
    </div>
  );
}

export function Toasts() {
  const { state, actions } = useApp();
  return (
    <div className="toast-stack" aria-live="polite" aria-atomic="false">
      {state.toasts.map((t) => (
        <div key={t.id} className={"toast " + t.kind} role={t.kind === "err" ? "alert" : "status"}>
          <span>{t.text}</span>
          <button className="toast-x" aria-label="Dismiss" onClick={() => actions.dismissToast(t.id)}><Icon name="close" /></button>
        </div>
      ))}
    </div>
  );
}

export function StaleBanner({ onRecompute, busy }: { onRecompute: () => void; busy: boolean }) {
  const { state } = useApp();
  if (!state.plan || !state.planStale) return null;
  return (
    <div className="note warn" role="status">
      <Icon name="alert" small={false} />
      <span>The data changed after this plan was computed, so it is out of date.</span>
      <button className="btn btn-secondary btn-sm" disabled={busy} onClick={onRecompute}>{busy ? "Computing…" : "Recompute"}</button>
    </div>
  );
}

export function PageHead({ title, lede, action }: { title: string; lede: string; action?: ReactNode }) {
  return (
    <div className={"page-head" + (action ? " with-act" : "")}>
      <div>
        <h1 tabIndex={-1}>{title}</h1>
        <p className="lede">{lede}</p>
      </div>
      {action}
    </div>
  );
}

export function BusyButton({ busy, busyLabel, label, icon = "play", ...rest }: {
  busy: boolean; busyLabel: string; label: string; icon?: "play"; className?: string; id?: string; onClick?: () => void; disabled?: boolean;
}) {
  return (
    <button type="button" {...rest} className={`${rest.className ?? "btn btn-primary"}${busy ? " is-loading" : ""}`} disabled={busy || rest.disabled}>
      <Icon name={busy ? "spin" : icon} /><span className="lbl">{busy ? busyLabel : label}</span>
    </button>
  );
}
