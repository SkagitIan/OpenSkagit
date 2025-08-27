/*
  OpenSkagit Service Worker — offline cache (no backend)
  Save this file as: /sw.js (site root)
  Serve over HTTPS (or localhost) for Service Worker to register.

  Strategy:
  - Precache the app shell (root HTML) on install
  - Stale‑while‑revalidate for same‑origin static assets
  - Network‑first for navigations with offline fallback to cached shell
  - Runtime cache for CDNs (e.g., Tailwind) with opaque responses allowed
*/

const VERSION = 'osg-v1';
const SHELL_CACHE = `osg-shell-${VERSION}`;
const RUNTIME_CACHE = `osg-runtime-${VERSION}`;

// Compute the root URL of the scope so we cache the correct index file
const ROOT_URL = new URL('.', self.registration.scope).toString();

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // Precache only the shell. Other assets will be cached at runtime.
    await cache.addAll([ROOT_URL]);
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // Clean up old caches
    const keys = await caches.keys();
    await Promise.all(
      keys.filter(k => ![SHELL_CACHE, RUNTIME_CACHE].includes(k)).map(k => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return; // don't touch POST/PUT/etc.

  const url = new URL(req.url);

  // App shell for navigations
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const res = await fetch(req);
        // Update shell cache in background when navigating successfully
        const cache = await caches.open(SHELL_CACHE);
        cache.put(ROOT_URL, res.clone());
        return res;
      } catch (err) {
        // Offline fallback to cached shell
        const cached = await caches.match(ROOT_URL);
        if (cached) return cached;
        // As a last resort, try any cached page
        const any = await caches.match(req);
        return any || new Response('<h1>Offline</h1><p>No cached content available.</p>', {headers:{'Content-Type':'text/html'}});
      }
    })());
    return;
  }

  // Same‑origin assets: stale‑while‑revalidate
  if (url.origin === self.location.origin) {
    event.respondWith((async () => {
      const cache = await caches.open(RUNTIME_CACHE);
      const cached = await cache.match(req);
      const network = fetch(req).then(res => {
        cache.put(req, res.clone()).catch(()=>{});
        return res;
      }).catch(() => cached);
      return cached || network;
    })());
    return;
  }

  // Cross‑origin (e.g., CDN) assets: stale‑while‑revalidate (allow opaque)
  event.respondWith((async () => {
    const cache = await caches.open(RUNTIME_CACHE);
    const cached = await cache.match(req);
    const network = fetch(req, {mode: req.mode === 'no-cors' ? 'no-cors' : 'cors'})
      .then(res => { cache.put(req, res.clone()).catch(()=>{}); return res; })
      .catch(() => cached);
    return cached || network;
  })());
});

// Optional: support immediate activation on update
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
