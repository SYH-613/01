const CACHE = 'yuezhi-an-shell-v1';
const SHELL = ['/service', '/static/style.css', '/static/app.js', '/manifest.webmanifest'];

self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request).then(response => {
    const url = new URL(event.request.url);
    const publicShell = url.origin === location.origin && (
      url.pathname === '/service' || url.pathname === '/manifest.webmanifest' || url.pathname.startsWith('/static/')
    );
    if (publicShell) {
      const copy = response.clone();
      caches.open(CACHE).then(cache => cache.put(event.request, copy));
    }
    return response;
  }).catch(() => caches.match(event.request)));
});
