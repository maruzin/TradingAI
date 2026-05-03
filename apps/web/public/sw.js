// TradingAI service worker — minimal cache-first shell.
//
// Caches the app shell (HTML, JS chunks, CSS, fonts) so the PWA opens
// instantly on repeat visits and works in airplane mode for read-only views.
// Live data (prices, briefs, alerts) is NEVER cached — those use network-only
// so a stale dashboard never shows wrong prices.

const VERSION = "tradingai-sw-v1";
const SHELL = [
  "/",
  "/manifest.json",
  "/favicon.ico",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) => cache.addAll(SHELL).catch(() => null)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Never cache live data or auth flows.
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/auth/")
  ) {
    return;
  }

  // Cache-first for the app shell + static chunks; fall back to network.
  if (
    url.pathname.startsWith("/_next/") ||
    SHELL.includes(url.pathname) ||
    url.pathname.endsWith(".css") ||
    url.pathname.endsWith(".js") ||
    url.pathname.endsWith(".woff2")
  ) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(VERSION).then((cache) => cache.put(req, copy));
          }
          return res;
        });
      }),
    );
  }
});
