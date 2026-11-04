/* BhojanChain service worker: always tries the network first so new versions appear automatically;
   the saved copy is used only when the phone is offline. API calls are never cached. */
const CACHE = 'bhojanchain-shell-v3';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin || u.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).then(r => { if (r.ok) { const c = r.clone(); caches.open(CACHE).then(ch => ch.put(e.request, c)); } return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match('/index.html') || caches.match('/'))));
});
