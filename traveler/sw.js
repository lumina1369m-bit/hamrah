// همراه | Service Worker: پوسته‌ی برنامه را برای نصب و اجرای آفلاین ذخیره می‌کند.
// داده‌ی رزرو و پرداخت هرگز کش نمی‌شود.
const VERSION = 'hamzaban-traveler-v20';
const SHELL = ['./', 'index.html', 'app.html', 'manifest.webmanifest', 'icon.svg', 'vendor/tailwind.css', 'vendor/theme.css', 'vendor/fonts.css', 'vendor/leaflet/leaflet.css', 'vendor/leaflet/leaflet.js', 'vendor/fonts/f1-LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko70yyygA.woff2', 'vendor/fonts/f2-LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko50yyygA.woff2', 'vendor/fonts/f3-LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko40yyygA.woff2', 'vendor/fonts/f4-LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko20yw.woff2', 'vendor/fonts/f5-Dxxo8j6PP2D_kU2muijlGMWWMmk.woff2', 'vendor/fonts/f6-Dxxo8j6PP2D_kU2muijlE8WWMmk.woff2', 'vendor/fonts/f7-Dxxo8j6PP2D_kU2muijlHcWW.woff2', 'vendor/fonts/f8-kJEPBvYX7BgnkSrUwT8OhrdQw4oELdPIeeII9v6oDMzBwG-RpA6RzaxHMPdY40KH8nGzv3fzfVJO1Q.woff2'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;
  // داده‌ی زنده‌ی API هرگز از کش نمی‌آید (وضعیت رزرو و پیشنهاد باید تازه باشد)
  if (url.pathname.startsWith('/api/')) return;
  // شبکه‌ی اول برای صفحه‌ها (تازه بماند)، کش برای بقیه
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('index.html')));
    return;
  }
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(e.request, copy)); }
      return res;
    }))
  );
});
