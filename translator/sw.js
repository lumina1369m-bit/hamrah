// مترجم همراه: کش پوسته‌ی برنامه برای کار آفلاین و نصب PWA
const CACHE = 'hz-translator-v47';
const SHELL = [
  './', 'index.html', 'app.html',
  'ui.css', 'ui.css?v=47', 'ui.js', 'ui.js?v=47',
  'app.js', 'app.js?v=47', 'config-features.js', 'config-features.js?v=47',
  'mission-map.js', 'mission-map.js?v=47', 'mission-actions.js', 'mission-actions.js?v=47',
  'presence.js', 'presence.js?v=47', 'support.js', 'support.js?v=47',
  'notifications.js', 'notifications.js?v=47',
  'code6-utilities.css', 'code6-utilities.css?v=47', 'code6.css', 'code6.css?v=47',
  'manifest.webmanifest', 'icon.svg', 'vendor/tailwind.css', 'vendor/theme.css', 'vendor/fonts.css',
  '/traveler/vendor/leaflet/leaflet.css', '/traveler/vendor/leaflet/leaflet.js',
  '/traveler/vendor/leaflet/images/marker-icon.png', '/traveler/vendor/leaflet/images/marker-icon-2x.png',
  '/traveler/vendor/leaflet/images/marker-shadow.png',
  'vendor/fonts/f1-LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko70yyygA.woff2',
  'vendor/fonts/f2-LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko50yyygA.woff2',
  'vendor/fonts/f3-LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko40yyygA.woff2',
  'vendor/fonts/f4-LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko20yw.woff2',
  'vendor/fonts/f5-Dxxo8j6PP2D_kU2muijlGMWWMmk.woff2',
  'vendor/fonts/f6-Dxxo8j6PP2D_kU2muijlE8WWMmk.woff2',
  'vendor/fonts/f7-Dxxo8j6PP2D_kU2muijlHcWW.woff2',
  'vendor/fonts/f8-kJEPBvYX7BgnkSrUwT8OhrdQw4oELdPIeeII9v6oDMzBwG-RpA6RzaxHMPdY40KH8nGzv3fzfVJO1Q.woff2'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith('hz-translator-') && k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return; // فونت‌ها و سرویس‌های خارجی مستقیم بارگذاری شوند
  if (url.pathname.startsWith('/api/')) return; // داده‌ی زنده‌ی API هرگز از کش نمی‌آید
  e.respondWith(
    fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return res;
    }).catch(() => caches.match(e.request).then((r) => r || caches.match('index.html')))
  );
});
