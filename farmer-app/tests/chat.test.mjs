// Drives the real app.js in jsdom against a fake backend: the change-request chat, in every state it can be in.
// Run: cd farmer-app/tests && npm i && npm test
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(root, "index.html"), "utf8");
const appJs = readFileSync(join(root, "app.js"), "utf8");

const CARD = { farmer_id: 7, status: "farmgate", crop: "tomato", qty_kg: 400, doorstep_per_kg: 14, break_even_per_kg: 16,
  changed: [], fpo_phone: "", phone: { registered: true, masked: "+91 *****1234" },
  payout: { total_inr: 5600, lines: [{ key: "doorstep_value", value: 5600 }] } };
const CHANGES = [{ field: "qty_kg", label: "Quantity", from: "400 kg", to: "300 kg" }, { field: "ready_hr", label: "Ready time", from: "06:00", to: "08:30" }];

/** A phone with the app loaded and a farmer already logged in. `script` answers POST /farmer/chat in order. */
async function boot({ chat = [], requests = [], confirmStatus = 200 } = {}) {
  const calls = [];
  const dom = new JSDOM(html, { url: "http://localhost/", pretendToBeVisual: true, runScripts: "outside-only" });
  const w = dom.window;
  w.localStorage.token = "tok"; w.localStorage.card = JSON.stringify(CARD); w.localStorage.cardAt = String(Date.now());
  w.matchMedia = () => ({ matches: false });
  const queue = [...chat], state = { requests: [...requests], offline: false };
  const json = (status, body) => Promise.resolve({ ok: status < 400, status, json: async () => body });
  w.fetch = (url, o = {}) => {
    const path = url.replace(/^.*\/farmer/, "/farmer"), method = o.method || "GET";
    calls.push({ path, method, body: o.body ? JSON.parse(o.body) : undefined, auth: new w.Headers(o.headers).get("Authorization") });
    if (state.offline) return Promise.reject(new TypeError("offline"));
    if (path === "/farmer/me") return json(200, CARD);
    if (path === "/farmer/requests" && method === "GET") return json(200, { requests: state.requests });
    if (path === "/farmer/chat") { const r = queue.shift(); return json(r.http || 200, r.body || r); }
    if (/\/confirm$/.test(path)) return json(confirmStatus, confirmStatus === 200 ? { status: "pending" } : { detail: "Your plan details changed since you asked." });
    if (/\/withdraw$/.test(path)) return json(200, { status: "withdrawn" });
    return json(404, {});
  };
  w.eval(readFileSync(join(root, "config.js"), "utf8"));
  w.eval(appJs);
  const $ = (s) => w.document.querySelector(s), $$ = (s) => [...w.document.querySelectorAll(s)];
  const settle = () => new Promise((r) => setTimeout(r, 25));
  const click = async (sel) => { $(sel).click(); await settle(); };
  const type = (sel, v) => { const el = $(sel); el.value = v; el.dispatchEvent(new w.Event("input", { bubbles: true })); };
  const pick = async (sel, v) => { const el = $(sel); el.value = v; el.dispatchEvent(new w.Event("change", { bubbles: true })); await settle(); };
  const text = () => w.document.body.textContent.replace(/\s+/g, " ");
  await settle();
  return { w, calls, state, $, $$, settle, click, type, pick, text };
}
const posts = (a, path) => a.calls.filter((c) => c.method === "POST" && c.path.includes(path));

test("the chat button shows on the card, opens the chat, and hides itself there", async () => {
  const a = await boot({ requests: [] });
  assert.equal(a.$("#fab").hidden, false);
  assert.match(a.$("#fab").getAttribute("aria-label"), /Ask for a change/);
  assert.ok(a.$("#fab svg"), "the button carries an icon");
  await a.click("#fab");
  assert.match(a.text(), /Ask for a change/);
  assert.ok(a.$("#cq"), "the message box is there");
  assert.equal(a.$("#fab").hidden, true);
  assert.ok(a.calls.some((c) => c.path === "/farmer/requests" && c.auth === "Bearer tok"));
});

test("a message becomes a confirm card with the numbers; Yes sends it; the request shows as waiting", async () => {
  const a = await boot({ chat: [{ status: "confirm", request_id: 41, changes: CHANGES }] });
  await a.click("#fab");
  a.type("#cq", "100 kg less and ready later");
  a.state.requests = [{ id: 41, status: "pending", changes: CHANGES, reason_code: null }];
  await a.click("[data-act=cSend]");
  assert.deepEqual(posts(a, "/farmer/chat")[0].body, { message: "100 kg less and ready later" });
  assert.match(a.text(), /This is what I understood/);
  assert.match(a.text(), /Quantity: 400 kg \u2192 300 kg/);
  assert.match(a.text(), /Ready time: 6:00 AM \u2192 8:30 AM/i);          // times shown the way the card shows them
  assert.ok(a.$("[data-act=cYes]") && a.$("[data-act=cNo]"));
  await a.click("[data-act=cYes]");
  assert.equal(posts(a, "/requests/41/confirm").length, 1);
  assert.match(a.text(), /Sent to your FPO/);
  assert.match(a.text(), /Your requests/);
  assert.match(a.text(), /Waiting for your FPO/);
  assert.ok(a.$("[data-act=cWd]"), "a waiting request can be cancelled");
  await a.click("[data-act=cWd]");
  assert.equal(posts(a, "/requests/41/withdraw").length, 1);
});

test("No discards the draft on the server and goes back to the message box", async () => {
  const a = await boot({ chat: [{ status: "confirm", request_id: 9, changes: CHANGES }] });
  await a.click("#fab"); a.type("#cq", "less"); await a.click("[data-act=cSend]");
  await a.click("[data-act=cNo]");
  assert.equal(posts(a, "/requests/9/withdraw").length, 1);
  assert.ok(a.$("#cq") && !a.$("[data-act=cYes]"));
});

test("a clarifying question is shown as plain text, never as HTML", async () => {
  const a = await boot({ chat: [{ status: "clarify", code: "llm", message: "How many kg? <img src=x onerror=alert(1)>" }] });
  await a.click("#fab"); a.type("#cq", "less"); await a.click("[data-act=cSend]");
  assert.match(a.text(), /How many kg\? <img src=x/);
  assert.equal(a.$$("img").length, 0);
  assert.match(a.text(), /less/, "the farmer's own message stays on screen");
});

test("a refusal is shown in the farmer's language, with the number filled in", async () => {
  const a = await boot({ chat: [{ status: "invalid", code: "qty_range", params: { max: 5000 }, message: "English fallback" }] });
  await a.click("#fab");
  await a.click("[data-lang=te]");
  a.type("#cq", "99999"); await a.click("[data-act=cSend]");
  assert.match(a.text(), /పరిమాణం 0 కంటే ఎక్కువ, గరిష్ఠంగా 5000 కిలోలు/);
  assert.doesNotMatch(a.text(), /English fallback/);
  await a.click("[data-lang=hi]");
  assert.match(a.text(), /अधिकतम 5000 किलो/, "switching language re-words messages already on screen");
});

test("when the language model is unavailable the form appears, and its values go as structured changes", async () => {
  const a = await boot({ chat: [{ status: "llm_unavailable", message: "x" }, { status: "confirm", request_id: 5, changes: CHANGES }, { status: "confirm", request_id: 6, changes: CHANGES }] });
  await a.click("#fab"); a.type("#cq", "hello"); await a.click("[data-act=cSend]");
  assert.match(a.text(), /Please use the form/);
  assert.ok(a.$("#cf") && a.$("#ch") && a.$("#cv"));
  assert.equal(a.$("#cv").type, "number");
  // "Remove 2 kg" -> shift -2
  await a.pick("#ch", "less"); a.type("#cv", "2"); await a.click("[data-act=cFormSend]");
  assert.deepEqual(posts(a, "/farmer/chat")[1].body, { structured: { changes: [{ field: "qty_kg", mode: "shift", value: -2 }] } });
  await a.click("[data-act=cNo]");
  // ready time "Set to" 06:30 -> set 6.5 (the box becomes a time box)
  assert.ok(a.$("#cf"), "still in the form after No: the language model is still off");
  await a.pick("#cf", "ready_hr"); await a.pick("#ch", "set");
  assert.equal(a.$("#cv").type, "time");
  a.type("#cv", "06:30"); await a.click("[data-act=cFormSend]");
  assert.deepEqual(posts(a, "/farmer/chat")[2].body, { structured: { changes: [{ field: "ready_hr", mode: "set", value: 6.5 }] } });
});

test("an empty or negative form value is refused before anything is sent", async () => {
  const a = await boot({ chat: [{ status: "llm_unavailable", message: "x" }] });
  await a.click("#fab"); a.type("#cq", "hi"); await a.click("[data-act=cSend]");
  await a.click("[data-act=cFormSend]");
  assert.match(a.text(), /Tell me what to change/);
  await a.pick("#ch", "more"); a.type("#cv", "-5"); await a.click("[data-act=cFormSend]");
  assert.equal(posts(a, "/farmer/chat").length, 1, "only the first message reached the server");
});

test("a rejected request shows the FPO's reason; a stale confirm asks the farmer to try again", async () => {
  const a = await boot({ requests: [{ id: 3, status: "rejected", changes: CHANGES, reason_code: "too_late" }], chat: [{ status: "confirm", request_id: 8, changes: CHANGES }], confirmStatus: 409 });
  await a.click("#fab");
  assert.match(a.text(), /Not possible: Too late/);
  a.type("#cq", "less"); await a.click("[data-act=cSend]"); await a.click("[data-act=cYes]");
  assert.match(a.text(), /Your details changed/);
  assert.ok(a.$("#cq"), "back to the message box");
});

test("an ended session sends the farmer back to log in; offline hides the button", async () => {
  const a = await boot({ chat: [{ http: 401, body: { detail: "expired" } }] });
  await a.click("#fab"); a.type("#cq", "less"); await a.click("[data-act=cSend]");
  assert.equal(a.w.localStorage.token, undefined, "token cleared");
  assert.equal(a.$("#fab").hidden, true);
  const b = await boot();
  assert.equal(b.$("#fab").hidden, false);
  b.state.offline = true; b.w.dispatchEvent(new b.w.Event("online")); await b.settle();
  assert.equal(b.$("#fab").hidden, true);
});

test("every language has every chat string, and the app source has no stray quotes in them", () => {
  const src = appJs.slice(appJs.indexOf("const L = {"), appJs.indexOf("const CROP"));
  const L = new Function(src + "; return L;")();
  const need = Object.keys(L.en);
  for (const lang of ["te", "hi", "ta"]) {
    const missing = need.filter((k) => !(k in L[lang]));
    // pre-existing app strings may legitimately fall back to English; the new chat strings must not
    const chatKeys = missing.filter((k) => /^(chat|c[A-Z]\w*|f(Qty|Ready|Dead)|h[QT][sml]|s[PARWE]|r[1-4]|e[0-6])$/.test(k));
    assert.deepEqual(chatKeys, [], `${lang} is missing ${chatKeys.join(", ")}`);
  }
});
