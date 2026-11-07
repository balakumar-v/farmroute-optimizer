// Caches the app shell only. API calls go to another origin and are never cached here: the saved card lives in
// the page's localStorage so logging out can delete it.
// Bump V whenever you change a shell file's name or want old caches gone.
const V = "farmroute-v8", SHELL = ["./", "index.html", "app.js", "config.js", "manifest.json", "icon-192.png", "icon-512.png"];
// add() one by one: a single missing file must not stop the worker installing (that would also block "Install app").
self.addEventListener("install", e => e.waitUntil(caches.open(V).then(c => Promise.allSettled(SHELL.map(u => c.add(u)))).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== V).map(x => caches.delete(x)))).then(() => self.clients.claim())));
// Network-first (3 s timeout), cache as fallback: online phones always get the newest files, offline phones still open
// the last copy. Fonts never change, so they are cache-first. The cache is refreshed even when the timeout fires.
self.addEventListener("fetch", e => {
  const r = e.request, u = new URL(r.url), font = /fonts\.(googleapis|gstatic)\.com$/.test(u.host);
  if (r.method !== "GET" || (u.origin !== location.origin && !font)) return;
  e.respondWith((async () => {
    const c = await caches.open(V), hit = await c.match(r, { ignoreSearch: true });
    if (font && hit) return hit;
    const net = fetch(r, font ? undefined : { cache: "no-cache" }).then(res => { if ((res.ok && !res.redirected) || res.type === "opaque") c.put(r, res.clone()); return res; });
    e.waitUntil(net.catch(() => {}));
    try { return await Promise.race([net, new Promise((_, no) => setTimeout(no, hit ? 3000 : 20000))]); }
    catch { return hit || (r.mode === "navigate" && await c.match("index.html")) || Response.error(); }
  })());
});
