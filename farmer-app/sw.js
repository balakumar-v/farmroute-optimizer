// Caches the app shell only. API calls go to another origin and are never cached here: the saved card lives in
// the page's localStorage so logging out can delete it.
const V = "farmroute-v1", SHELL = ["./", "index.html", "app.js", "config.js", "manifest.webmanifest", "icon-192.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== V).map(x => caches.delete(x)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  const ok = e.request.method === "GET" && (u.origin === location.origin || /fonts\.(googleapis|gstatic)\.com$/.test(u.host));
  if (!ok) return;
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
    if (r.ok || r.type === "opaque") caches.open(V).then(c => c.put(e.request, r.clone()));
    return r;
  }).catch(() => caches.match("index.html"))));
});
