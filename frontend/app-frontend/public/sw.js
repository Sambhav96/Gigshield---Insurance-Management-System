// gigshield-rider-pwa-sw.js
const CACHE_NAME = 'gigshield-rider-offline-v1';
const STATIC_ASSETS = [
  '/',
  '/login/rider',
  '/rider',
  '/rider/earnings',
  '/rider/shield',
  '/rider/activity',
  '/rider/profile'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Offline shell caching
      return cache.addAll(STATIC_ASSETS).catch(err => {
         console.warn("Offline shell pre-cache partial fail (acceptable in dev): ", err);
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            return caches.delete(name);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Stale-while-revalidate pattern for PWA shell navigation
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => {
        return caches.match('/rider');
      })
    );
  } else {
    event.respondWith(
      caches.match(event.request).then((response) => {
        return response || fetch(event.request);
      })
    );
  }
});
