// Deliberately a pass-through. This service worker exists so the app is installable, and
// an INSTALLED app is the one case where Chrome grants persistent storage without a
// prompt -- which is what stops the browser evicting a user's documents under disk
// pressure. Engagement alone does not earn it (measured: three engaged visits, still
// denied), so installation is the lever.
//
// It must not cache or rewrite anything. The engine is ~115 MB over the wire, served with precise
// Content-Encoding and cross-origin-isolation headers; a caching service worker is an
// excellent way to corrupt that. No respondWith call anywhere: every request goes to the
// network exactly as it would without a worker.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => { /* pass-through on purpose -- see above */ });
// Escape hatch: postMessage({type:'unregister'}) removes it if it ever misbehaves.
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'unregister') { self.registration.unregister(); }
});
