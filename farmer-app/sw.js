// Caches the app shell only. API calls go to another origin and are never cached here: the saved card lives in
// the page's localStorage so logging out can delete it.
// Bump V whenever you change a shell file's name or want old caches gone.
const V = "farmroute-v3", SHELL = ["./", "index.html", "app.js", "config.js", "manifest.json", "icon-192.png", "icon-512.png"];
// add() one by one: a single missing file must not stop the worker installing (that would also block "Install app").
self.addEventListener("install", e => e.waitUntil(caches.open(V).then(c => Promise.allSettled(SHELL.map(u => c.add(u)))).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== V).map(x => caches.delete(x)))).then(() => self.clients.claim())));
// Stale-while-revalidate: open instantly from cache (works offline), refresh the cache in the background.
self.addEventListener("fetch", e => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET") return;
  if (u.origin !== location.origin && !/fonts\.(googleapis|gstatic)\.com$/.test(u.host)) return;
  e.respondWith((async () => {
    const c = await caches.open(V), hit = await c.match(r, { ignoreSearch: true });
    const net = fetch(r).then(res => { if ((res.ok && !res.redirected) || res.type === "opaque") c.put(r, res.clone()); return res; });
    if (hit) { e.waitUntil(net.catch(() => {})); return hit; }
    try { return await net; } catch { return (r.mode === "navigate" && await c.match("index.html")) || Response.error(); }
  })());
});
