'use strict';
// امنیت: محدودکنندهٔ تلاش، هدرهای امنیتی، و بررسی ایمنی پیکربندی در حالت انتشار.
// این ماژول وابستگی به پایگاه داده ندارد تا به‌راحتی تست شود.

// محدودکننده‌ی تلاش در حافظه‌ی فرایند. کلید معمولاً IP است.
// فقط «شکست‌ها» شمرده می‌شوند (مثلاً رمز اشتباه)، تا ورود درست کاربر مسدود نشود.
function makeLimiter({ max, windowMs }) {
  const hits = new Map(); // key -> { count, reset }
  function prune(t) {
    if (hits.size < 50000) return;
    for (const [k, e] of hits) if (e.reset <= t) hits.delete(k);
  }
  return {
    // آیا این کلید هنوز مجاز است؟ { ok, retryAfter }
    check(key) {
      const t = Date.now();
      const e = hits.get(key);
      if (!e || e.reset <= t) return { ok: true, retryAfter: 0 };
      if (e.count >= max) return { ok: false, retryAfter: Math.ceil((e.reset - t) / 1000) };
      return { ok: true, retryAfter: 0 };
    },
    // یک شکست ثبت می‌شود
    fail(key) {
      const t = Date.now();
      prune(t);
      let e = hits.get(key);
      if (!e || e.reset <= t) { e = { count: 0, reset: t + windowMs }; hits.set(key, e); }
      e.count += 1;
    },
    reset(key) { hits.delete(key); },
    _size() { return hits.size; },
  };
}

// IP واقعی اتصال. هدر X-Forwarded-For عمداً نادیده گرفته می‌شود تا قابل جعل نباشد.
// اگر پشت پروکسی مورد اعتماد هستید، این تابع را با فهرست پروکسی‌ها تکمیل کنید.
// اگر HZ_TRUST_PROXY=1 باشد، یعنی یک پروکسی مورد اعتماد جلوی سرور است که IP کاربر را به X-Forwarded-For
// اضافه می‌کند؛ در این حالت آخرین مقدار آن (که پروکسی نوشته) استفاده می‌شود. در غیر این صورت هدر نادیده گرفته می‌شود.
function clientIp(req) {
  const socketIp = (req.socket && req.socket.remoteAddress) || 'unknown';
  if (process.env.HZ_TRUST_PROXY === '1') {
    const xff = String(req.headers['x-forwarded-for'] || '');
    const parts = xff.split(',').map((x) => x.trim()).filter(Boolean);
    const last = parts[parts.length - 1];
    if (last && /^[0-9a-fA-F:.]{3,45}$/.test(last)) return last;
  }
  return socketIp;
}

// هدرهای امنیتی برای همه‌ی پاسخ‌ها. frameAncestors برای نمایش در پیش‌نمایش ابزار تنظیم می‌شود.
function securityHeaders(pathname, frameAncestors) {
  const h = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'geolocation=(self), camera=(), microphone=(), payment=(), usb=()',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'Content-Security-Policy': [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob: https://tile.openstreetmap.org",
      "connect-src 'self' https://nominatim.openstreetmap.org",
      "font-src 'self' data:",
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      `frame-ancestors ${frameAncestors}`,
    ].join('; '),
  };
  if (pathname.startsWith('/api/')) h['Cache-Control'] = 'no-store';
  return h;
}

// رمز مدیر ضعیف است؟ (کوتاه یا در فهرست رمزهای شناخته‌شده‌ی آزمایشی)
function isWeakAdminPassword(pw) {
  const p = String(pw || '');
  return p.length < 12 || WEAK_ADMIN.has(p);
}

// بررسی ایمنی پیکربندی هنگام راه‌اندازی در حالت انتشار (غیر توسعه).
// اگر خطایی برگردد، سرور بالا نمی‌آید (fail closed).
const WEAK_ADMIN = new Set(['admin1234', 'test-admin-pass', 'password', '12345678']);
function productionErrors(env) {
  const errs = [];
  if (env.HZ_DEV === '1') return errs;
  const pw = env.HZ_ADMIN_PASSWORD || '';
  if (pw.length < 12) errs.push('HZ_ADMIN_PASSWORD باید حداقل ۱۲ کاراکتر باشد');
  if (WEAK_ADMIN.has(pw)) errs.push('HZ_ADMIN_PASSWORD ضعیف یا آزمایشی است');
  if ((env.HZ_DOC_KEY || '').length < 32) errs.push('HZ_DOC_KEY باید حداقل ۳۲ کاراکتر و تنظیم‌شده باشد');
  return errs;
}

module.exports = { makeLimiter, clientIp, securityHeaders, productionErrors, isWeakAdminPassword };
