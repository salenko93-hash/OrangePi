const CACHE = "lyceumtv-mobile-v3.7.4";
const SHELL = [
  "/mobile/",
  "/mobile/mobile.css",
  "/mobile/mobile.js",
  "/mobile/manifest.webmanifest",
  "/mobile/icons/icon-192.png",
  "/mobile/icons/icon-512.png",
  "/mobile/icons/icon-maskable-512.png",
  "/img/logo_white.png",
  "/campus/",
  "/css/operations.css",
  "/js/campus.js",
];
self.addEventListener("install", (e) =>
  e.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting()),
  ),
);
self.addEventListener("activate", (e) =>
  e.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("lyceumtv-mobile-") && k !== CACHE)
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  ),
);
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (
    u.pathname.startsWith("/api/mobile/") ||
    u.pathname === "/api/campus" ||
    u.pathname === "/api/notifications"
  ) {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copy = r.clone();
          if (r.ok) caches.open(CACHE).then((c) => c.put(e.request, copy));
          return r;
        })
        .catch(() => caches.match(e.request)),
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(
      (cached) =>
        cached ||
        fetch(e.request).then((r) => {
          if (r.ok && u.origin === location.origin)
            caches.open(CACHE).then((c) => c.put(e.request, r.clone()));
          return r;
        }),
    ),
  );
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data?.url || "/mobile/";
  e.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        for (const c of list) {
          if ("focus" in c) {
            c.navigate(url);
            return c.focus();
          }
        }
        return clients.openWindow ? clients.openWindow(url) : undefined;
      }),
  );
});
