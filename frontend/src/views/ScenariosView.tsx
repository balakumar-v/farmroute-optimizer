import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { PageHead } from "../components/Shell";
import { SCENARIOS, SCENARIO_CATEGORIES } from "../lib/scenarios";
import type { ViewName } from "../lib/types";
import { useApp } from "../state/store";

export interface ScenarioMeta {
  key: string; name: string; sub: string; num: string | null;
  farmers: number; vehicles: number; markets: number; real: boolean; blurb: string;
}

/** Labels look like "1. Cold chain: refrigeration-aware pooling", "3. Fleet scarcity + incompatible pickup windows"
 *  (no colon) or "Bihar mandis, Mar 2026: potato & onion". Peel the number, then split name from detail. */
export function scenarioMeta(key: string): ScenarioMeta {
  const sc = SCENARIOS[key];
  const numMatch = sc.label.match(/^(\d+)\.\s*(.*)$/);
  const rest = numMatch ? numMatch[2] : sc.label;
  let name = rest, sub = "";
  const colon = rest.indexOf(":");
  const plus = rest.indexOf(" + ");
  if (colon > -1) { name = rest.slice(0, colon); sub = rest.slice(colon + 1); }
  else if (plus > -1) { name = rest.slice(0, plus); sub = rest.slice(plus + 3); }
  sub = sub.trim();
  sub = sub.charAt(0).toUpperCase() + sub.slice(1);
  return {
    key, name: name.trim(), sub, num: numMatch ? numMatch[1] : null,
    farmers: sc.farmers.length,
    vehicles: sc.vehicles.reduce((n, v) => n + v.count, 0),
    markets: sc.markets.length,
    real: sc.category === "real",
    blurb: sc.blurb || "",
  };
}

export function ScenariosView({ go }: { go: (v: ViewName) => void }) {
  const { state, actions } = useApp();
  const hasData = state.farmers.length + state.vehicles.length + state.markets.length > 0;
  const [armed, setArmed] = useState(false);
  const armTimer = useRef<number>(0);
  useEffect(() => () => window.clearTimeout(armTimer.current), []);

  const known = new Set(SCENARIO_CATEGORIES.map((c) => c.id));
  const groups = [
    ...SCENARIO_CATEGORIES.map((c) => ({ id: c.id, label: c.label, keys: Object.keys(SCENARIOS).filter((k) => SCENARIOS[k].category === c.id) })),
    { id: "other", label: "Other", keys: Object.keys(SCENARIOS).filter((k) => !known.has(SCENARIOS[k].category)) },
  ].filter((g) => g.keys.length);

  async function run(key: string) {
    const ok = await actions.runScenario(key);
    if (ok) go("map");
  }

  function onReset() {
    if (!armed) {
      setArmed(true);
      window.clearTimeout(armTimer.current);
      armTimer.current = window.setTimeout(() => setArmed(false), 4000);
      return;
    }
    window.clearTimeout(armTimer.current);
    setArmed(false);
    void actions.resetAll();
  }

  const pct = state.run ? Math.round((state.run.done / state.run.total) * 100) : 0;

  return (
    <>
      <PageHead title="Scenarios" lede="Small farmers each need a truck and a market. The optimizer pools nearby farmers onto shared trips and decides which market takes which produce. Pick a scenario: it loads the data, computes the plan, and opens the map." />
      <div id="scenarioList" className="sc-list">
        {groups.map((g) => (
          <div key={g.id} role="group" aria-label={g.label}>
            <h2 className="sc-cat">{g.label}</h2>
            {g.keys.map((key) => {
              const m = scenarioMeta(key);
              const running = state.run?.key === key;
              return (
                <article key={key} className={"sc-row" + (running ? " running" : "")} data-key={key}>
                  {m.num ? <div className="sc-num" aria-hidden="true">{m.num}</div> : <div className="sc-num is-real" aria-hidden="true">REAL</div>}
                  <div className="sc-title"><h2>{m.name}</h2><p>{m.sub}</p></div>
                  <div className="sc-stat"><b>{m.farmers}</b><span>farmers</span></div>
                  <div className="sc-stat"><b>{m.vehicles}</b><span>vehicles</span></div>
                  <div className="sc-stat"><b>{m.markets}</b><span>markets</span></div>
                  <div className="sc-tagcell">
                    {m.real
                      ? <span className="tag real" title="Mandi prices and capacities are real; farmers and fleet are synthetic">Real prices</span>
                      : <span className="tag">Synthetic</span>}
                  </div>
                  <div className="sc-run">
                    <button className={"btn btn-primary" + (running ? " is-loading" : "")} type="button" disabled={!!state.run} onClick={() => run(key)}>
                      <Icon name={running ? "spin" : "play"} />
                      <span className="lbl run-lbl">{running ? "Running…" : hasData ? "Replace & run" : "Run"}</span>
                    </button>
                  </div>
                  {running && state.run && (
                    <div className="run-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Scenario progress">
                      <div className="run-bar"><i style={{ width: `${pct}%` }} /></div>
                      <span>{state.run.label}</span>
                    </div>
                  )}
                  <details className="sc-more"><summary>{m.real ? "About the data" : "What this tests"}<Icon name="chevron" /></summary><p>{m.blurb}</p></details>
                </article>
              );
            })}
          </div>
        ))}
      </div>
      <div className="sc-foot">
        <p id="demoStatus" className={"status" + (state.runError ? " err" : "")} role="status" aria-live="polite">
          {state.runError || (state.run ? "" : state.plan ? "Last plan computed. Open the Map or Plan tab, or run another scenario." : "")}
        </p>
        <button id="resetDataBtn" className={"btn btn-danger" + (armed ? " armed" : "")} type="button" onClick={onReset} disabled={!!state.run}>
          {armed ? "Click again to clear everything" : "Clear all backend data"}
        </button>
      </div>
    </>
  );
}
