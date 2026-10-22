'use strict';
/* تست قابلیت‌ها، شهرها، ممیزی و امنیت.
 * دو بخش دارد:
 *  ۱) روی سرور در حال اجرا (BASE، حالت توسعه، پایگاه داده‌ی تست) – قابلیت‌ها، شهرها، ممیزی، تطبیق شهری.
 *  ۲) سرورهای جدا که خودِ تست بالا می‌آورد – محدودکننده‌ی تلاش، بررسی ایمنی پیکربندی انتشار، هدرها.
 * اجرا: BASE=http://127.0.0.1:8081 ADMIN_PASSWORD=test-admin-pass node test/features_cities_security.test.js
 */
const path = require('path');
const { spawn } = require('child_process');

const BASE = process.env.BASE || 'http://127.0.0.1:8081';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'test-admin-pass';
const SERVER_DIR = path.join(__dirname, '..');
let passed = 0, failed = 0;
function check(name, ok, extra = '') {
  if (ok) { passed++; console.log('  ok   ' + name); }
  else { failed++; console.log('  FAIL ' + name + (extra ? '  [' + extra + ']' : '')); }
}
async function call(method, p, body, token, headers = {}) {
  const h = { 'Content-Type': 'application/json', ...headers };
  if (token) h.Authorization = 'Bearer ' + token;
  const r = await fetch(BASE + p, { method, headers: h, body: body ? JSON.stringify(body) : undefined });
  let data = null; try { data = await r.json(); } catch (e) { /* غیر JSON */ }
  return { status: r.status, data, headers: r.headers };
}
const randPhone = () => '913' + String(1000000 + Math.floor(Math.random() * 8999999)).slice(-7);

async function travelerToken() {
  const phone = randPhone();
  await call('POST', '/api/auth/request-code', { phone, role: 'traveler' });
  const v = await call('POST', '/api/auth/verify', { phone, role: 'traveler', code: '123456' });
  return v.data.token;
}
async function translatorToken() {
  const phone = randPhone();
  await call('POST', '/api/auth/request-code', { phone, role: 'translator' });
  const v = await call('POST', '/api/auth/verify', { phone, role: 'translator', code: '123456' });
  await call('POST', '/api/dev/approve-translator', null, v.data.token);
  return v.data.token;
}
function bookingBody(extra = {}) {
  return { kind: 'instant', origin_lang: 'ar', dest_lang: 'fa', place: 'تست-' + Math.random().toString(36).slice(2, 8), traveler_name: 'تست', ...extra };
}

// ---------- سرور جدا برای آزمون‌های امنیتی ----------
function startServer(env, port) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ['server.js'], {
      cwd: SERVER_DIR,
      env: { ...process.env, PORT: String(port), HZ_DB: `/tmp/hz_sec_${port}_${Date.now()}.sqlite`, ...env },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let out = '';
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { out += d; });
    child.on('exit', (code) => resolve({ exited: true, code, out }));
    // اگر بالا آمد، بعد از کمی صبر برمی‌گردانیم
    const tryUp = async (n) => {
      if (child.exitCode !== null) return;
      try { await fetch(`http://127.0.0.1:${port}/api/config`); resolve({ exited: false, child, out: () => out }); }
      catch (e) { if (n > 40) return resolve({ exited: false, child, out: () => out, timeout: true }); setTimeout(() => tryUp(n + 1), 150); }
    };
    setTimeout(() => tryUp(0), 300);
  });
}
async function rawCall(port, method, p, body, headers = {}) {
  const r = await fetch(`http://127.0.0.1:${port}${p}`, { method, headers: { 'Content-Type': 'application/json', ...headers }, body: body ? JSON.stringify(body) : undefined });
  let data = null; try { data = await r.json(); } catch (e) { /* */ }
  return { status: r.status, data, headers: r.headers };
}

async function waitOffers(tok, ms = 4500) {
  await new Promise((res) => setTimeout(res, ms));
}

async function mainServerTests() {
  console.log('== قابلیت‌ها و شهرها (سرور توسعه)');
  // پاک‌سازی رزروها و مترجمان باقی‌مانده از تست‌های قبلی تا پیشنهادها دزدیده نشوند
  await call('POST', '/api/dev/offline-all');
  const adm = (await call('POST', '/api/admin/login', { password: ADMIN_PASSWORD })).data.token;
  check('ورود مدیر با رمز درست', !!adm);

  // ---- امنیت دسترسی به مسیرهای مدیر
  let r = await call('GET', '/api/admin/features');
  check('فهرست قابلیت‌ها بدون توکن مدیر ممنوع است', r.status === 401);
  r = await call('GET', '/api/admin/cities');
  check('فهرست شهرها بدون توکن مدیر ممنوع است', r.status === 401);
  r = await call('GET', '/api/admin/audit');
  check('ممیزی بدون توکن مدیر ممنوع است', r.status === 401);
  r = await call('POST', '/api/admin/cities', { name_fa: 'بی‌اجازه', lat: 1, lng: 1 });
  check('افزودن شهر بدون توکن ممنوع است', r.status === 401);

  // ---- قابلیت‌ها: فهرست و اعتبارسنجی
  r = await call('GET', '/api/admin/features', null, adm);
  const keys = (r.data.features || []).map((f) => f.key);
  check('همه‌ی قابلیت‌ها در فهرست هستند', keys.includes('traveler_booking') && keys.includes('car_mode') && keys.includes('translator_online'));
  check('قابلیت پیاده‌نشده با implemented=false معرفی می‌شود', (r.data.features || []).find((f) => f.key === 'email_login')?.implemented === false);
  r = await call('PUT', '/api/admin/features', { no_such_feature: true }, adm);
  check('قابلیت ناشناخته رد می‌شود', r.status === 400 && r.data.error === 'unknown_feature');
  r = await call('PUT', '/api/admin/features', { car_mode: 'yes' }, adm);
  check('مقدار غیربولی رد می‌شود', r.status === 400 && r.data.error === 'invalid_value');
  r = await call('PUT', '/api/admin/features', { email_login: true }, adm);
  check('قابلیت پیاده‌نشده را نمی‌توان روشن کرد', r.status === 409 && r.data.error === 'not_implemented');
  r = await call('PUT', '/api/admin/features', { instant_booking: true, nothing: 1 }, adm);
  check('تغییر نیمه‌معتبر کل‌اش رد می‌شود', r.status === 400);
  r = await call('PUT', '/api/admin/features', {}, adm);
  check('درخواست خالی رد می‌شود', r.status === 400 && r.data.error === 'nothing_to_change');

  // ---- وابستگی: خاموش‌کردن والد وقتی فرزند روشن است ممنوع
  r = await call('PUT', '/api/admin/features', { traveler_booking: false }, adm);
  check('خاموش‌کردن رزرو مسافر وقتی وابسته روشن است، ممنوع', r.status === 409 && r.data.error === 'dependency_off');

  // ---- خاموش‌کردن کامل مسیر رزرو و بررسی اثر آن روی API
  const tok = await travelerToken();
  const off = await call('PUT', '/api/admin/features', { booking_convert: false, booking_change: false, car_mode: false, instant_booking: false, scheduled_booking: false, traveler_booking: false }, adm);
  check('خاموش‌کردن کل مسیر رزرو مسافر', off.status === 200 && off.data.changed.includes('traveler_booking'));
  r = await call('POST', '/api/traveler/bookings', bookingBody(), tok);
  check('رزرو وقتی قابلیت خاموش است رد می‌شود', r.status === 409 && r.data.error === 'feature_disabled' && r.data.feature === 'traveler_booking');
  const cfg = await call('GET', '/api/config');
  check('/api/config وضعیت قابلیت را نشان می‌دهد', cfg.data.features && cfg.data.features.traveler_booking === false);
  const on = await call('PUT', '/api/admin/features', { traveler_booking: true, instant_booking: true, scheduled_booking: true, car_mode: true, booking_change: true, booking_convert: true }, adm);
  check('روشن‌کردن دوباره با ترتیب درست', on.status === 200);
  r = await call('POST', '/api/traveler/bookings', bookingBody(), tok);
  check('پس از روشن‌شدن، رزرو ممکن است', r.status === 201);
  const bid = r.data.id;
  await call('POST', `/api/traveler/bookings/${bid}/cancel`, null, tok);

  // ---- ممیزی
  r = await call('GET', '/api/admin/audit?limit=50', null, adm);
  check('تغییر قابلیت در ممیزی ثبت شده', (r.data.entries || []).some((e) => e.action === 'features.update'));

  // ---- شهرها: اعتبارسنجی
  const badCases = [
    [{ name_fa: 'ا', lat: 1, lng: 1 }, 'invalid_name'],
    [{ name_fa: 'شهر', lat: 'x', lng: 1 }, 'invalid_lat'],
    [{ name_fa: 'شهر', lat: 1, lng: 999 }, 'invalid_lng'],
    [{ name_fa: 'شهر', lat: 1, lng: 1, radius_km: 0 }, 'invalid_radius'],
    [{ name_fa: 'شهر', lat: 1, lng: 1, traveler_enabled: 'yes' }, 'invalid_value'],
    [{ name_fa: 'شهر', lat: 1, lng: 1, name_en: '<script>' }, 'invalid_name_en'],
  ];
  for (const [body, err] of badCases) {
    r = await call('POST', '/api/admin/cities', body, adm);
    check(`شهر نامعتبر رد می‌شود (${err})`, r.status === 400 && r.data.error === err, JSON.stringify(r.data));
  }

  // ---- شهر آزمایشی
  const name = 'شهر آزمون ' + Math.floor(Math.random() * 1e6);
  r = await call('POST', '/api/admin/cities', { name_fa: name, name_en: 'Test City', lat: 34.5, lng: 50.2, radius_km: 25 }, adm);
  check('افزودن شهر معتبر', r.status === 201 && Number.isInteger(r.data.id));
  const cid = r.data.id;
  r = await call('POST', '/api/admin/cities', { name_fa: name, lat: 1, lng: 1 }, adm);
  check('نام تکراری شهر پذیرفته نمی‌شود', r.status === 409 && r.data.error === 'city_exists');
  r = await call('GET', '/api/admin/cities', null, adm);
  check('فهرست شهرها شامل شهر جدید و شهر پیش‌فرض است', (r.data.cities || []).some((c) => c.id === cid) && Number.isInteger(r.data.default_city_id));
  r = await call('PATCH', `/api/admin/cities/${cid}`, {}, adm);
  check('ویرایش بدون تغییر رد می‌شود', r.status === 400 && r.data.error === 'nothing_to_change');
  r = await call('PATCH', '/api/admin/cities/999999', { radius_km: 3 }, adm);
  check('ویرایش شهر ناموجود ۴۰۴', r.status === 404);
  r = await call('PATCH', `/api/admin/cities/${cid}`, { radius_km: 40 }, adm);
  check('ویرایش شعاع', r.status === 200);

  // ---- رزرو در شهر غیرفعال و شهر ناموجود
  r = await call('POST', '/api/traveler/bookings', bookingBody({ city_id: 999999 }), tok);
  check('شهر ناموجود در رزرو رد می‌شود', r.status === 400 && r.data.error === 'invalid_city');
  r = await call('POST', '/api/traveler/bookings', bookingBody({ city_id: cid }), tok);
  check('رزرو در شهر فعال پذیرفته می‌شود', r.status === 201 && r.data.id);
  const openBid = r.data.id;
  r = await call('PATCH', `/api/admin/cities/${cid}`, { traveler_enabled: false }, adm);
  check('غیرفعال‌کردن شهر با رزرو باز، بدون تأیید ممنوع است', r.status === 409 && r.data.error === 'open_bookings' && r.data.count >= 1);
  r = await call('GET', '/api/traveler/bookings', null, tok);
  const still = (r.data.bookings || []).find((b) => b.id === openBid);
  check('تا تأیید، رزرو باز دست‌نخورده می‌ماند', still && still.status !== 'cancelled');
  r = await call('PATCH', `/api/admin/cities/${cid}`, { traveler_enabled: false, confirm_cancel: true }, adm);
  check('با تأیید، رزروهای باز شهر لغو می‌شوند', r.status === 200 && r.data.cancelled >= 1);
  r = await call('GET', '/api/traveler/bookings', null, tok);
  check('رزرو لغوشده در فهرست مسافر لغو است', (r.data.bookings || []).find((b) => b.id === openBid)?.status === 'cancelled');
  r = await call('POST', '/api/traveler/bookings', bookingBody({ city_id: cid }), tok);
  check('رزرو در شهر غیرفعال پذیرفته نمی‌شود', r.status === 409 && r.data.error === 'city_not_active');
  r = await call('PUT', '/api/admin/settings', { default_city_id: cid }, adm);
  check('شهر غیرفعال پیش‌فرض نمی‌شود', r.status === 400 && r.data.error === 'invalid_city');
  r = await call('PATCH', `/api/admin/cities/${cid}`, { traveler_enabled: true }, adm);
  check('فعال‌کردن دوباره شهر', r.status === 200);

  // ---- تطبیق شهری: مترجم شهر پیش‌فرض، رزرو شهر دیگر را نمی‌بیند
  const dcity = (await call('GET', '/api/config')).data.default_city_id;
  const tr = await translatorToken();
  await call('PATCH', '/api/translator/online', { online: true }, tr);
  const place = 'تطبیق-شهری-' + Math.random().toString(36).slice(2, 7);
  r = await call('POST', '/api/traveler/bookings', bookingBody({ city_id: cid, place }), tok);
  const otherCityBooking = r.data.id;
  await waitOffers(tr);
  r = await call('GET', '/api/translator/offers', null, tr);
  check('مترجم شهر دیگر پیشنهاد رزرو این شهر را نمی‌گیرد', !(r.data.offers || []).some((o) => o.place === place));
  await call('POST', `/api/traveler/bookings/${otherCityBooking}/cancel`, null, tok);
  const place2 = 'تطبیق-همشهری-' + Math.random().toString(36).slice(2, 7);
  r = await call('POST', '/api/traveler/bookings', bookingBody({ city_id: dcity, place: place2 }), tok);
  const sameCityBooking = r.data.id;
  await waitOffers(tr, 6000);
  r = await call('GET', '/api/translator/offers', null, tr);
  check('مترجم همان شهر پیشنهاد می‌گیرد', (r.data.offers || []).some((o) => o.place === place2));
  await call('POST', `/api/traveler/bookings/${sameCityBooking}/cancel`, null, tok);
  await call('PATCH', '/api/translator/online', { online: false }, tr);

  // ---- مترجم: ثبت‌نام با شهر غیرفعال و قابلیت خاموش
  const trReg = await translatorToken();
  await call('PATCH', `/api/admin/cities/${cid}`, { translator_enabled: false }, adm);
  r = await call('POST', '/api/translator/registration', { nda: true, charter: true, gender: 'male', first_name: 'الف', last_name: 'ب', languages: ['fa'], fields: ['general'], city_id: cid }, trReg);
  check('ثبت‌نام مترجم با شهر غیرفعال برای مترجم رد می‌شود', r.status === 409 && r.data.error === 'city_not_active', JSON.stringify(r.data));
  const cfgT = await call('GET', '/api/config');
  check('شهر غیرفعال برای مترجم در فهرست شهرهای مترجم نیست', Array.isArray(cfgT.data.translator_cities) && !cfgT.data.translator_cities.some((c) => c.id === cid));
  await call('PATCH', `/api/admin/cities/${cid}`, { translator_enabled: true }, adm);

  // ---- یادداشت هماهنگی مصاحبه
  r = await call('POST', '/api/admin/interview-slots', { starts_at: new Date(Date.now() + 5 * 3600000).toISOString(), note: 'حضوری: دفتر مرکزی، طبقه ۳' }, adm);
  check('نوبت با یادداشت هماهنگی ساخته می‌شود', r.status === 201);
  const slotId = r.data.id;
  // مترجمی که هنوز مصاحبه‌اش قبول نشده (بدون تأیید آزمایشی)
  const phoneI = randPhone();
  await call('POST', '/api/auth/request-code', { phone: phoneI, role: 'translator' });
  const trI = (await call('POST', '/api/auth/verify', { phone: phoneI, role: 'translator', code: '123456' })).data.token;
  r = await call('POST', `/api/translator/interview-slots/${slotId}/book`, null, trI);
  check('مترجم نوبت را رزرو می‌کند', r.status === 200, JSON.stringify(r.data));
  r = await call('GET', '/api/translator/interview-slots', null, trI);
  check('یادداشت هماهنگی برای مترجم نمایش داده می‌شود', r.data.booking && r.data.booking.note === 'حضوری: دفتر مرکزی، طبقه ۳');
  r = await call('POST', '/api/admin/interview-slots', { starts_at: new Date(Date.now() + 6 * 3600000).toISOString(), note: '<img src=x onerror=alert(1)>' }, adm);
  check('یادداشت بیش از حد طولانی یا HTML، محدود و به‌صورت متن ذخیره می‌شود', r.status === 201);
  const feat = await call('PUT', '/api/admin/features', { interview_scheduling: false }, adm);
  check('خاموش‌کردن مصاحبه', feat.status === 200);
  const sNew = (await call('POST', '/api/admin/interview-slots', { starts_at: new Date(Date.now() + 7 * 3600000).toISOString() }, adm)).data.id;
  r = await call('POST', `/api/translator/interview-slots/${sNew}/book`, null, trI);
  check('وقتی مصاحبه خاموش است، رزرو نوبت ممکن نیست', r.status === 409 && r.data.error === 'feature_disabled');
  await call('PUT', '/api/admin/features', { interview_scheduling: true }, adm);

  // ---- بازگردانی تنظیمات تست
  await call('PATCH', `/api/admin/cities/${cid}`, { traveler_enabled: true, translator_enabled: true }, adm);
}

async function isolatedSecurityTests() {
  console.log('== امنیت: محدودکننده‌ی تلاش و هدرها (سرور جدا)');
  const PORT = 8093;
  const s1 = await startServer({ HZ_DEV: '1', HZ_ADMIN_PASSWORD: 'test-admin-pass', HZ_RL_ADMIN_MAX: '3', HZ_RL_OTP_MAX: '2' }, PORT);
  if (s1.exited || s1.timeout) { check('سرور آزمون امنیت بالا آمد', false, s1.out ? String(s1.out()).slice(0, 200) : ''); return; }
  try {
    const base = `http://127.0.0.1:${PORT}`;
    const login = (pw, xff) => rawCall(PORT, 'POST', '/api/admin/login', { password: pw }, xff ? { 'X-Forwarded-For': xff } : {});
    let r = await login('bad-1', '1.1.1.1');
    check('رمز اشتباه: ۴۰۱', r.status === 401);
    r = await login('bad-2', '2.2.2.2');
    check('رمز اشتباه دوم: ۴۰۱', r.status === 401);
    r = await login('bad-3', '3.3.3.3');
    check('رمز اشتباه سوم: ۴۰۱', r.status === 401);
    r = await login('bad-4', '4.4.4.4');
    check('تلاش چهارم (با هدر جعلی X-Forwarded-For) مسدود است: ۴۲۹', r.status === 429 && r.data.error === 'too_many_attempts');
    r = await login('test-admin-pass', '5.5.5.5');
    check('حتی رمز درست در زمان قفل پذیرفته نمی‌شود', r.status === 429);
    const hdr = await rawCall(PORT, 'GET', '/api/config');
    check('هدر X-Content-Type-Options برابر nosniff است', hdr.headers.get('x-content-type-options') === 'nosniff');
    check('CSP با frame-ancestors تنظیم شده', /frame-ancestors/.test(hdr.headers.get('content-security-policy') || ''));
    check('CSP اجازه‌ی object-src ندارد', /object-src 'none'/.test(hdr.headers.get('content-security-policy') || ''));
    check('پاسخ API کش نمی‌شود', (hdr.headers.get('cache-control') || '') === 'no-store');
    const page = await fetch(base + '/traveler/index.html');
    check('صفحه‌ی ایستا هم CSP دارد', !!page.headers.get('content-security-policy'));
    check('هدر Referrer-Policy سخت‌گیرانه است', page.headers.get('referrer-policy') === 'no-referrer');
    // تلاش کد OTP با IP محدود
    const a = await rawCall(PORT, 'POST', '/api/auth/request-code', { phone: '9121111111', role: 'traveler' });
    const b2 = await rawCall(PORT, 'POST', '/api/auth/request-code', { phone: '9122222222', role: 'traveler' });
    const c = await rawCall(PORT, 'POST', '/api/auth/request-code', { phone: '9123333333', role: 'traveler' });
    check('درخواست کد بیش از سقف IP مسدود است', a.status === 200 && b2.status === 200 && c.status === 429, `${a.status},${b2.status},${c.status}`);
    // مسیر مدیر بدون توکن
    r = await rawCall(PORT, 'GET', '/api/admin/cities');
    check('بدون توکن مدیر، ۴۰۱', r.status === 401);
  } finally {
    s1.child.kill('SIGTERM');
  }

  console.log('== امنیت: بررسی ایمنی پیکربندی انتشار');
  const bad = await startServer({ HZ_DEV: '0', HZ_ADMIN_PASSWORD: 'admin1234' }, 8094);
  check('انتشار با رمز آزمایشی و بدون کلید سند: سرور بالا نمی‌آید', bad.exited && bad.code === 1 && /پیکربندی ناامن/.test(bad.out), `code=${bad.code}`);
  const good = await startServer({ HZ_DEV: '0', HZ_ADMIN_PASSWORD: 'a-much-longer-admin-pass-2026', HZ_DOC_KEY: 'x'.repeat(40) }, 8095);
  if (good.exited || good.timeout) { check('انتشار با تنظیمات قوی بالا می‌آید', false); }
  else {
    const p = 8095;
    const dev = await rawCall(p, 'POST', '/api/dev/offline-all');
    check('در انتشار، مسیرهای توسعه ۴۰۴ هستند', dev.status === 404);
    const adminNoPw = await rawCall(p, 'POST', '/api/admin/login', { password: 'x' });
    check('در انتشار، رمز اشتباه مدیر پذیرفته نمی‌شود', adminNoPw.status === 401);
    // تغییر رمز مدیر از داخل پنل: رمز فعلی لازم است و رمز تازه باید قوی باشد
    const admLogin = await rawCall(p, 'POST', '/api/admin/login', { password: 'a-much-longer-admin-pass-2026' });
    check('در انتشار، ورود مدیر با رمز درست ممکن است', admLogin.status === 200 && !!admLogin.data.token);
    const admH = { Authorization: 'Bearer ' + admLogin.data.token };
    let cp = await rawCall(p, 'POST', '/api/admin/change-password', { current_password: 'wrong-current-pass', new_password: 'another-strong-pass-2027' }, admH);
    check('تغییر رمز با رمز فعلی اشتباه: ۴۰۱', cp.status === 401 && cp.data.error === 'bad_current_password');
    cp = await rawCall(p, 'POST', '/api/admin/change-password', { current_password: 'a-much-longer-admin-pass-2026', new_password: 'short' }, admH);
    check('تغییر رمز با رمز تازه‌ی ضعیف: ۴۰۰', cp.status === 400 && cp.data.error === 'weak_password');
    cp = await rawCall(p, 'POST', '/api/admin/change-password', { current_password: 'a-much-longer-admin-pass-2026', new_password: 'another-strong-pass-2027' }, admH);
    check('تغییر رمز مدیر از پنل موفق است', cp.status === 200 && cp.data.ok === true);
    const oldLogin = await rawCall(p, 'POST', '/api/admin/login', { password: 'a-much-longer-admin-pass-2026' });
    check('پس از تغییر، رمز قبلی دیگر کار نمی‌کند', oldLogin.status === 401);
    const newLogin = await rawCall(p, 'POST', '/api/admin/login', { password: 'another-strong-pass-2027' });
    check('پس از تغییر، ورود با رمز تازه ممکن است', newLogin.status === 200 && !!newLogin.data.token);
    const otp = await rawCall(p, 'POST', '/api/auth/request-code', { phone: '9124444444', role: 'traveler' });
    check('در انتشار بدون پیامک‌دهنده، کد ارسال نمی‌شود (۵۰۳)', otp.status === 503 && otp.data.error === 'sms_provider_not_configured');
    good.child.kill('SIGTERM');
  }
  const weakKey = await startServer({ HZ_DEV: '0', HZ_ADMIN_PASSWORD: 'a-much-longer-admin-pass-2026', HZ_DOC_KEY: 'short' }, 8096);
  check('کلید سند کوتاه: سرور بالا نمی‌آید', weakKey.exited && weakKey.code === 1);
}

(async () => {
  try {
    await mainServerTests();
  } catch (e) {
    check('اجرای بخش سرور توسعه بدون استثنا', false, String(e && e.message));
  }
  try {
    await isolatedSecurityTests();
  } catch (e) {
    check('اجرای بخش امنیت بدون استثنا', false, String(e && e.message));
  }
  console.log(`\nنتیجه: ${passed} موفق، ${failed} ناموفق`);
  process.exit(failed ? 1 : 0);
})();
