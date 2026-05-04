// TradingAI service worker — minimal cache-first shell.
//
// Caches static JS/CSS chunks + manifest so the PWA opens instantly on repeat
// visits. Live data (prices, briefs, alerts) is NEVER cached — those use
// network-only so a stale dashboard never shows wrong prices.
//
// IMPORTANT: bump VERSION any time we ship a fix that needs to override a
// previously-shipped bug. The activate handler nukes every cache that doesn't
// match the current VERSION, so an old client running this file pulls fresh
// chunks on next reload. The HTML root (/) is intentionally NOT cached —
// it references content-hashed chunks, so a stale HTML pointing at deleted
// chunks would 404 and break the app.
//
// VERSION history:
//   v1 — initial PWA shell
//   v2 — drop / from SHELL; force cache invalidation after dashboard auth fix

const VERSION = "tradingai-sw-v2";
const SHELL = [
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

  // Never cache the HTML root — it references content-hashed JS chunks, and
  // a stale HTML pointing at deleted chunks would 404 and break the app on
  // every deploy. Let the network handle it (standard Next.js HTML caching
  // headers from Vercel's CDN are sufficient).
  if (url.pathname === "/") return;

  // Cache-first for hashed static chunks + manifest/favicon. Chunks are
  // content-hashed by Next so a cached chunk is correct forever.
  if (
    url.pathname.startsWith("/_next/static/") ||
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
