import { fmt } from "../lib/format";
import type { TemperatureInfo } from "../lib/types";

/**
 * "Current temperature": the room temperature the plan's spoilage was computed with.
 * Demo only: the value is simulated (a DHT22-like reading, new on every compute); the real build reads a DHT22 on an ESP32.
 */
export function TemperaturePanel({ t }: { t: TemperatureInfo }) {
  const delta = t.previous_temp_c == null ? null : t.temp_c - t.previous_temp_c;
  const pctVsRef = (t.rate_factor - 1) * 100;
  const top = Math.max(...t.curve.map((c) => c.spoilage_kg), t.at_reference_spoilage_kg, 1e-9);
  const total = t.unrefrigerated_spoilage_kg + t.refrigerated_spoilage_kg;
  const nowIdx = t.curve.reduce((best, c, i) => (Math.abs(c.temp_c - t.temp_c) < Math.abs(t.curve[best].temp_c - t.temp_c) ? i : best), 0);
  return (
    <div className="sec" id="dashTemperature">
      <div className="sec-head"><h2>Current temperature</h2><span className="tag cold">{t.sensor} sensor</span><span className="grow" /></div>
      <div className="statement">
        <div>
          <h2>Reading</h2>
          <div className="temp-read" aria-live="polite">
            <span className="temp-val">{fmt(t.temp_c, 1)}<small>°C</small></span>
            {delta !== null && (
              <span className={"temp-delta " + (delta > 0 ? "up" : "down")}>
                {delta > 0 ? "▲" : "▼"} {fmt(Math.abs(delta), 1)}°C since the last plan ({fmt(t.previous_temp_c, 1)}°C)
              </span>
            )}
          </div>
          <dl>
            <div className="line"><dt>Spoilage rate vs {fmt(t.reference_c, 0)}°C</dt><dd className={pctVsRef > 0.5 ? "bad-text" : undefined}>{pctVsRef >= 0 ? "+" : "−"}{fmt(Math.abs(pctVsRef), 0)}% (×{fmt(t.rate_factor, 2)})</dd></div>
            <div className="line"><dt>Trips in unrefrigerated vehicles</dt><dd>{t.unrefrigerated_trips} ({fmt(t.unrefrigerated_spoilage_kg, 1)} kg spoiled)</dd></div>
            <div className="line"><dt>Trips in refrigerated vehicles</dt><dd>{t.refrigerated_trips} ({fmt(t.refrigerated_spoilage_kg, 1)} kg spoiled)</dd></div>
            <div className="line sub"><dt>Spoilage in this plan</dt><dd>{fmt(total, 1)} kg</dd></div>
            <div className="line sub"><dt>The same trips at {fmt(t.reference_c, 0)}°C</dt><dd>{fmt(t.at_reference_spoilage_kg, 1)} kg</dd></div>
          </dl>
        </div>
        <div>
          <h2>Same trips at other room temperatures</h2>
          <ul className="temp-bars" aria-label="Spoilage in kg if the same trips ran at each temperature">
            {t.curve.map((c, i) => (
              <li key={c.temp_c} className={i === nowIdx ? "now" : undefined}>
                <span className="tb-t">{fmt(c.temp_c, 0)}°C</span>
                <span className="tb-track"><i style={{ width: `${Math.max(2, (c.spoilage_kg / top) * 100)}%` }} /></span>
                <span className="tb-v">{fmt(c.spoilage_kg, 1)} kg</span>
              </li>
            ))}
          </ul>
          <p className="hint">Highlighted: closest to the current reading ({fmt(t.temp_c, 1)}°C). Refrigerated trips stay flat; unrefrigerated ones roughly double their spoilage rate for every +{fmt(10, 0)}°C.</p>
        </div>
      </div>
    </div>
  );
}
