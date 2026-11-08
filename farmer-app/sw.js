// Caches the app shell only. API calls go to another origin and are never cached here: the saved card lives in
// the page's localStorage so logging out can delete it.
// Bump V whenever you change a shell file's name or want old caches gone.
const V = "farmroute-v9", SHELL = ["./", "index.html", "app.js", "config.js", "manifest.json", "icon-192.png", "icon-512.png"];
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

// Web Push (backend push.py): show the farmer's own one-line update; tapping it opens (or refreshes) the app.
// Nothing is cached here, and the text comes from the server in the farmer's language.
self.addEventListener("push", e => {
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch { d = { body: e.data && e.data.text() }; }
  e.waitUntil((async () => {
    for (const c of await self.clients.matchAll({ type: "window", includeUncontrolled: true })) c.postMessage("farmroute-refresh");
    await self.registration.showNotification(d.title || "Farmroute", { body: d.body || "", tag: d.tag || "farmroute-plan", renotify: true, icon: "icon-192.png", badge: "icon-192.png", data: { url: d.url || "./" } });
  })());
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    if (all.length) { const c = all[0]; c.postMessage("farmroute-refresh"); return c.focus(); }
    return self.clients.openWindow((e.notification.data && e.notification.data.url) || "./");
  })());
});
