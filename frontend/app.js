const LABELS = ["Our System", "Proximity Pooling", "Individual Transport"];
const KEYS = ["our_system", "proximity_pooling", "individual_transport"];

const state = {
  apiBase: "",
  lastPlan: null,
  charts: { net: null, cov: null }
};

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function fmt(n, digits = 0) {
  if (n === undefined || n === null || isNaN(n)) return "\u2013";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

// ---------- tabs ----------
document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("view-" + btn.dataset.view).classList.add("active");
});

// ---------- API base ----------
function loadApiBase() {
  try {
    const saved = localStorage.getItem("fpoApiBase");
    if (saved) state.apiBase = saved;
  } catch (e) { /* storage unavailable, fine */ }
  document.getElementById("apiBase").value = state.apiBase;
}
document.getElementById("saveApi").addEventListener("click", () => {
  state.apiBase = document.getElementById("apiBase").value.trim().replace(/\/$/, "");
  try { localStorage.setItem("fpoApiBase", state.apiBase); } catch (e) {}
  document.getElementById("apiStatus").textContent = "Saved.";
  setTimeout(() => (document.getElementById("apiStatus").textContent = ""), 2000);
  loadAllTables();
});

async function api(path, opts) {
  if (!state.apiBase) throw new Error("Set the backend API base URL above first.");
  const res = await fetch(state.apiBase + path, opts);
  if (!res.ok) throw new Error(path + " failed (" + res.status + ")");
  return res.json();
}

// ---------- data entry: farmers / vehicles / markets ----------
function formToPayload(form) {
  const data = new FormData(form);
  const payload = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") payload[el.name] = el.checked;
    else if (el.type === "number") payload[el.name] = data.get(el.name) === "" ? null : Number(data.get(el.name));
    else payload[el.name] = data.get(el.name);
  }
  return payload;
}

function wireEntryForm(formId, path, reload) {
  const form = document.getElementById(formId);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formToPayload(form))
      });
      form.reset();
      await reload();
    } catch (err) {
      alert(err.message);
    }
  });
}

async function reloadFarmers() {
  const tbody = document.querySelector("#farmerTable tbody");
  try {
    const rows = await api("/farmers");
    tbody.innerHTML = rows.map((f) => `<tr>
      <td>${f.name ?? ""}</td><td>${f.location ?? ""}</td><td>${f.crop ?? ""}</td>
      <td>${fmt(f.quantity_kg, 1)}</td><td>${f.pickup_window ?? ""}</td>
      <td>${f.refrigeration_needed ? "Yes" : "No"}</td></tr>`).join("");
  } catch (e) { /* backend not reachable yet */ }
}
async function reloadVehicles() {
  const tbody = document.querySelector("#vehicleTable tbody");
  try {
    const rows = await api("/vehicles");
    tbody.innerHTML = rows.map((v) => `<tr>
      <td>${v.type ?? ""}</td><td>${fmt(v.capacity_kg, 1)}</td>
      <td>${v.refrigerated ? "Yes" : "No"}</td><td>${fmt(v.cost_per_km, 2)}</td></tr>`).join("");
  } catch (e) {}
}
async function reloadMarkets() {
  const tbody = document.querySelector("#marketTable tbody");
  try {
    const rows = await api("/markets");
    tbody.innerHTML = rows.map((m) => `<tr>
      <td>${m.name ?? ""}</td><td>${m.location ?? ""}</td><td>${m.crop ?? ""}</td>
      <td>${fmt(m.price_per_kg, 2)}</td><td>${fmt(m.capacity_kg, 1)}</td></tr>`).join("");
  } catch (e) {}
}
function loadAllTables() { reloadFarmers(); reloadVehicles(); reloadMarkets(); }

wireEntryForm("farmerForm", "/farmers", reloadFarmers);
wireEntryForm("vehicleForm", "/vehicles", reloadVehicles);
wireEntryForm("marketForm", "/markets", reloadMarkets);

// ---------- compute plan ----------
async function runCompute(triggerBtn) {
  const btn = document.getElementById(triggerBtn);
  const original = btn.textContent;
  btn.textContent = "Computing\u2026";
  btn.disabled = true;
  try {
    const data = await api("/plan/compute", { method: "POST" });
    state.lastPlan = data;
    renderDashboard(data);
    renderComparison(data);
  } catch (err) {
    document.getElementById("poolCards").innerHTML =
      `<p style="color:var(--danger)">${err.message}</p>`;
    document.getElementById("compareEmpty").textContent = err.message;
    document.getElementById("compareEmpty").style.color = "var(--danger)";
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
}
document.getElementById("computeBtn").addEventListener("click", () => runCompute("computeBtn"));
document.getElementById("compareBtn").addEventListener("click", () => runCompute("compareBtn"));

// ---------- dashboard rendering ----------
function renderDashboard(data) {
  const os = data.our_system;
  const s = os.summary || {};
  document.getElementById("dashSummary").innerHTML = `
    <div class="stat net"><div class="num">\u20B9${fmt(s.net_return)}</div><div class="lbl">Total net return</div></div>
    <div class="stat net"><div class="num">\u20B9${fmt(s.net_return_per_farmer)}</div><div class="lbl">Net return / farmer</div></div>
    <div class="stat coverage"><div class="num">${fmt(s.pct_qty_served, 1)}%</div><div class="lbl">Produce actually sold</div></div>
    <div class="stat"><div class="num">${fmt(s.pools_formed)}</div><div class="lbl">Pools formed</div></div>
    <div class="stat"><div class="num">${fmt(s.vehicles_used)}</div><div class="lbl">Vehicles used</div></div>
    <div class="stat"><div class="num">${fmt(s.total_spoilage_kg, 1)}</div><div class="lbl">Spoilage (kg)</div></div>`;

  document.getElementById("dashCoverageNote").textContent =
    `Only ${fmt(s.pct_qty_served, 1)}% of pooled produce reached a paying market this run \u2014 ` +
    `treat this figure with the same weight as net return; a high net return with low coverage means most volume never sold.`;

  const cards = (os.pools || []).map((p) => {
    const markets = (p.markets_used || []).map((m) => `<span class="badge">Market ${m}</span>`).join(" ");
    return `<div class="pool-card">
      <h4>Pool \u2014 vehicle ${p.vehicle_id}${p.infeasible ? ' <span class="badge" style="color:var(--danger)">infeasible</span>' : ""}</h4>
      <dl>
        <dt>Farmers</dt><dd>${(p.farmer_ids || []).length}</dd>
        <dt>Total qty</dt><dd>${fmt(p.total_qty_kg, 1)} kg</dd>
        <dt>Revenue</dt><dd>\u20B9${fmt(p.revenue)}</dd>
        <dt>Transport cost</dt><dd>\u20B9${fmt(p.transport_cost)}</dd>
        <dt>Net return</dt><dd>\u20B9${fmt(p.net_return)}</dd>
        <dt>Spoilage</dt><dd>${fmt(p.spoilage_loss_kg, 1)} kg</dd>
        <dt>Unsold at market</dt><dd class="${p.unsold_kg > 0 ? "bad" : ""}">${fmt(p.unsold_kg, 1)} kg</dd>
        <dt>Never got a truck</dt><dd class="${p.unserved_no_vehicle_kg > 0 ? "bad" : ""}">${fmt(p.unserved_no_vehicle_kg, 1)} kg</dd>
      </dl>
      <div class="markets">${markets}</div>
    </div>`;
  }).join("");
  document.getElementById("poolCards").innerHTML = cards || '<p class="muted">No pools in this plan.</p>';
}

// ---------- comparison rendering ----------
function renderComparison(data) {
  document.getElementById("compareEmpty").style.display = "none";
  const netReturns = KEYS.map((k) => data[k]?.summary?.net_return ?? 0);
  const coverage = KEYS.map((k) => data[k]?.summary?.pct_qty_served ?? 0);
  const colors = [cssVar("--accent"), cssVar("--warn"), cssVar("--danger")];

  if (state.charts.net) state.charts.net.destroy();
  state.charts.net = new Chart(document.getElementById("netReturnChart"), {
    type: "bar",
    data: { labels: LABELS, datasets: [{ data: netReturns, backgroundColor: colors }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
  });

  if (state.charts.cov) state.charts.cov.destroy();
  state.charts.cov = new Chart(document.getElementById("coverageChart"), {
    type: "bar",
    data: { labels: LABELS, datasets: [{ data: coverage, backgroundColor: colors }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, max: 100 } } }
  });
}

// ---------- init ----------
loadApiBase();
if (state.apiBase) loadAllTables();
