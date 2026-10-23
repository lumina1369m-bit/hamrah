'use strict';
/*
 * سرور توسعه‌ی همراه (مسافر و مترجم)
 * - فایل‌های استاتیک هر دو اپ را سرو می‌کند: /traveler/ و /translator/
 * - API احراز هویت با کد پیامکی، وضعیت مترجم و ماموریت‌ها را با SQLite نگه می‌دارد
 *
 * وضعیت پیامک: هنوز سرویس پیامک انتخاب نشده است. تا وقتی HZ_DEV=1 باشد کد ثابت «123456»
 * استفاده می‌شود و تأیید کارشناس/ماموریت‌های آزمایشی هم فعال‌اند. در حالت غیر-توسعه،
 * ارسال کد به سرویس پیامک نیاز دارد و بدون پیکربندی با خطای 503 پاسخ می‌دهد.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const Database = require('better-sqlite3');
const { makeLimiter, clientIp, securityHeaders, productionErrors, isWeakAdminPassword } = require('./lib/security');
const { FEATURES, FEATURE_KEYS, resolveFeatures, validateFeaturePatch } = require('./lib/features');
const { createSmsSender } = require('./lib/sms');

const PORT = Number(process.env.PORT || 8080);
const DEV = process.env.HZ_DEV === '1';
const DB_PATH = process.env.HZ_DB || path.join(__dirname, 'data', 'hamzaban.sqlite');
const APP_ROOT = path.resolve(__dirname, '..');
const STATIC_ROOTS = { '/traveler/': path.join(APP_ROOT, 'traveler'), '/translator/': path.join(APP_ROOT, 'translator'), '/admin/': path.join(APP_ROOT, 'admin') };

// ثابت‌های پیکربندی (در پنل مدیریت یا قانون تعریف می‌شوند؛ اینجا فقط مقدار اولیه‌اند)
const CONFIG = {
  OTP_TTL_SEC: 120,          // مدت اعتبار کد و زمان ارسال مجدد (سند مترجم)
  OTP_RESEND_SEC: 120,
  OTP_MAX_ATTEMPTS: 5,       // سند: ۵ تلاش ناموفق
  OTP_LOCK_SEC: 10 * 60,     // سند: قفل ۱۰ دقیقه‌ای
  SESSION_HOURS: 12,         // مدت نشست؛ تحقیق ۳۰ روزه هنوز باز است
  DEV_CODE: '123456',
};

// بررسی ایمنی پیکربندی در حالت انتشار، پیش از ساخت پایگاه داده و کلید مدارک انجام می‌شود تا
// سرور با تنظیمات ناامن اصلاً بالا نیاید (fail closed). این بررسی باید همین‌جا و زود انجام شود؛
// وگرنه خروج زودهنگامِ نبودِ HZ_DOC_KEY در بخش مدارک جلوی پیام یکپارچه‌ی «پیکربندی ناامن» را می‌گیرد.
if (require.main === module) {
  const cfgErrors = productionErrors(process.env);
  if (cfgErrors.length) { console.error('پیکربندی ناامن؛ سرور بالا نمی‌آید:\n - ' + cfgErrors.join('\n - ')); process.exit(1); }
}

// فرستنده‌ی پیامک از متغیرهای محیطی ساخته می‌شود (lib/sms.js)؛ تا وقتی شرکت و کلید تنظیم نشده،
// در حالت غیرتوسعه پاسخ 503 sms_provider_not_configured داده می‌شود.
const SMS = createSmsSender(process.env);

fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');
db.exec(`
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phone TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('traveler','translator')),
  created_at INTEGER NOT NULL,
  UNIQUE(phone, role)
);
CREATE TABLE IF NOT EXISTS otp_codes (
  phone TEXT NOT NULL,
  role TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  locked_until INTEGER,
  PRIMARY KEY (phone, role)
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS translators (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'registered',
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS translator_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'uploaded',
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  blob BLOB NOT NULL,
  reject_reason TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  translator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  purpose TEXT,
  traveler_name TEXT,
  place TEXT,
  start_at INTEGER NOT NULL,
  total INTEGER NOT NULL DEFAULT 0,
  net INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'accepted'
);
CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  traveler_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  payload TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
`);

// ستون‌های آنلاین و زبان‌ها برای مترجم (اگر قبلاً نبودند)
for (const sql of [
  "ALTER TABLE translators ADD COLUMN online INTEGER NOT NULL DEFAULT 0",
  "ALTER TABLE translators ADD COLUMN langs TEXT NOT NULL DEFAULT '[\"fa\",\"ar\",\"en\"]'",
  "ALTER TABLE translators ADD COLUMN gender TEXT",
  "ALTER TABLE translators ADD COLUMN accept_any INTEGER NOT NULL DEFAULT 1",
  "ALTER TABLE translators ADD COLUMN score INTEGER NOT NULL DEFAULT 100",
]) { try { db.exec(sql); } catch (e) { /* ستون از قبل وجود دارد */ } }
db.exec(`
CREATE TABLE IF NOT EXISTS reservations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  traveler_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('instant','scheduled')),
  origin_lang TEXT NOT NULL,
  dest_lang TEXT NOT NULL,
  field TEXT NOT NULL DEFAULT 'general',
  place TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  traveler_name TEXT NOT NULL DEFAULT '',
  gender_pref TEXT NOT NULL DEFAULT 'any',
  scheduled_at INTEGER,
  status TEXT NOT NULL,
  translator_id INTEGER REFERENCES users(id),
  matched_at INTEGER,
  search_started_at INTEGER NOT NULL,
  total INTEGER NOT NULL,
  net INTEGER NOT NULL,
  cancel_after_match INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
  translator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending',
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  decided_at INTEGER
);
`);

// ستون‌های تازه‌ی رزرو (بعد از ساخت جدول)
for (const sql of [
  "ALTER TABLE reservations ADD COLUMN traveler_gender TEXT",
  "ALTER TABLE reservations ADD COLUMN hours INTEGER NOT NULL DEFAULT 1",
  "ALTER TABLE reservations ADD COLUMN car INTEGER NOT NULL DEFAULT 0",
  "ALTER TABLE reservations ADD COLUMN party INTEGER NOT NULL DEFAULT 1",
  "ALTER TABLE reservations ADD COLUMN finished_at INTEGER",
  "ALTER TABLE reservations ADD COLUMN pay_method TEXT",
  "ALTER TABLE reservations ADD COLUMN traveler_paid INTEGER NOT NULL DEFAULT 0",
  "ALTER TABLE reservations ADD COLUMN translator_confirmed INTEGER NOT NULL DEFAULT 0",
  "ALTER TABLE reservations ADD COLUMN pay_state TEXT",
  "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
  "ALTER TABLE translators ADD COLUMN profile TEXT",
  "ALTER TABLE translators ADD COLUMN fields TEXT NOT NULL DEFAULT '[\"general\"]'",
  "ALTER TABLE translators ADD COLUMN interview TEXT",
  "CREATE TABLE IF NOT EXISTS translator_notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, doc_id INTEGER, kind TEXT NOT NULL, created_at INTEGER NOT NULL, UNIQUE(doc_id, kind))",
  "CREATE TABLE IF NOT EXISTS interview_slots (id INTEGER PRIMARY KEY AUTOINCREMENT, starts_at INTEGER NOT NULL, booked_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, room_token TEXT, status TEXT NOT NULL DEFAULT 'open', created_at INTEGER NOT NULL)",
  "ALTER TABLE translator_notifications ADD COLUMN ref TEXT",
  "CREATE TABLE IF NOT EXISTS translator_interviews (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, result TEXT NOT NULL, created_at INTEGER NOT NULL)",
  "ALTER TABLE translator_documents ADD COLUMN expires_at INTEGER",
  "ALTER TABLE reservations ADD COLUMN base INTEGER",
  "ALTER TABLE reservations ADD COLUMN tax INTEGER",
  "ALTER TABLE reservations ADD COLUMN service_code TEXT",
  "ALTER TABLE reservations ADD COLUMN service_started_at INTEGER",
  "ALTER TABLE reservations ADD COLUMN service_code_attempts INTEGER NOT NULL DEFAULT 0",
  "ALTER TABLE reservations ADD COLUMN finish_requested_at INTEGER",
  "ALTER TABLE reservations ADD COLUMN finished_by TEXT",
  "ALTER TABLE reservations ADD COLUMN lat REAL",
  "ALTER TABLE reservations ADD COLUMN lng REAL",
  "CREATE TABLE IF NOT EXISTS admin_sessions (token_hash TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)",
]) { try { db.exec(sql); } catch (e) { /* ستون از قبل وجود دارد */ } }

db.exec(`
CREATE TABLE IF NOT EXISTS change_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
  changes TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  decided_at INTEGER
);
CREATE TABLE IF NOT EXISTS extension_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
  extra_hours INTEGER NOT NULL,
  extra_base INTEGER NOT NULL,
  extra_tax INTEGER NOT NULL,
  extra_net INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  decided_at INTEGER
);
`);

// ---------- شهرها، ممیزی و ستون‌های جدید (سند: شهرها از پنل مدیر فعال/غیرفعال می‌شوند) ----------
db.exec(`
CREATE TABLE IF NOT EXISTS cities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name_fa TEXT NOT NULL UNIQUE,
  name_en TEXT NOT NULL DEFAULT '',
  province TEXT NOT NULL DEFAULT '',
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  radius_km INTEGER NOT NULL DEFAULT 30,
  traveler_enabled INTEGER NOT NULL DEFAULT 1,
  translator_enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER NOT NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}'
);
`);
for (const sql of [
  'ALTER TABLE reservations ADD COLUMN city_id INTEGER REFERENCES cities(id)',
  'ALTER TABLE translators ADD COLUMN city_id INTEGER REFERENCES cities(id)',
  "ALTER TABLE interview_slots ADD COLUMN note TEXT NOT NULL DEFAULT ''",
]) { try { db.exec(sql); } catch (e) { /* ستون از قبل وجود دارد */ } }
// شهرهای نمونه فقط وقتی جدول خالی است؛ مدیر می‌تواند نام و مختصات را تغییر دهد یا غیرفعال کند
const CITY_SEED = [
  ['تهران', 'Tehran', 'تهران', 35.6892, 51.3890],
  ['مشهد', 'Mashhad', 'خراسان رضوی', 36.2605, 59.6168],
  ['اصفهان', 'Isfahan', 'اصفهان', 32.6546, 51.6680],
  ['شیراز', 'Shiraz', 'فارس', 29.5918, 52.5836],
  ['تبریز', 'Tabriz', 'آذربایجان شرقی', 38.0962, 46.2738],
  ['کرج', 'Karaj', 'البرز', 35.8327, 50.9915],
];
if (!db.prepare('SELECT COUNT(*) AS n FROM cities').get().n) {
  const ins = db.prepare('INSERT INTO cities (name_fa, name_en, province, lat, lng, radius_km, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 30, ?, ?)');
  for (const c of CITY_SEED) ins.run(c[0], c[1], c[2], c[3], c[4], Date.now(), Date.now());
}
// وضعیت‌های «باز» رزرو: هنوز مترجم ندارند؛ هنگام غیرفعال‌کردن شهر لغو می‌شوند
const UNMATCHED = ['searching', 'waiting_schedule', 'matching', 'unmatched_ask', 'no_match'];
const UNMATCHED_SQL = UNMATCHED.map((s) => `'${s}'`).join(',');

const now = () => Date.now();
const sha256 = (s) => crypto.createHash('sha256').update(s).digest('hex');
const randomToken = () => crypto.randomBytes(32).toString('base64url');

// ---------- ابزار پاسخ ----------
function send(res, status, body, headers = {}) {
  const data = body === undefined ? '' : JSON.stringify(body);
  res.writeHead(status, Object.assign({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }, headers));
  res.end(data);
}
function readJson(req, limit = 64 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on('data', (c) => { size += c.length; if (size > limit) { reject(Object.assign(new Error('payload_too_large'), { status: 413 })); req.destroy(); } else chunks.push(c); });
    req.on('end', () => {
      if (!chunks.length) return resolve({});
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
      catch (e) { reject(Object.assign(new Error('bad_json'), { status: 400 })); }
    });
    req.on('error', reject);
  });
}

// ---------- اعتبارسنجی ----------
// موبایل ایران: ۹ رقم بعد از ۰ که با ۹ شروع می‌شود (ورودی فارسی/عربی هم پذیرفته می‌شود)
function normalizePhone(raw, role) {
  const ascii = String(raw || '').replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
  const digits = ascii.replace(/\D/g, '');
  // شماره‌ی ایرانی: ۹xxxxxxxxx (هر سه نقش)
  const m = digits.match(/^(?:0098|98|0)?(9\d{9})$/);
  if (m) return m[1];
  // سایر کشورها (فقط مسافر): با علامت + و کد کشور؛ مترجم فقط ایرانی است
  if (role === 'traveler' && /^\s*\+/.test(ascii) && digits.length >= 8 && digits.length <= 15) return '+' + digits;
  return null;
}
const ROLES = new Set(['traveler', 'translator']);
const STATUSES = new Set(['registered', 'in_progress', 'pending_review', 'active_general', 'active_specialized', 'rejected', 'suspended', 'deleted']);

// ---------- نشست ----------
function userTokenOf(req) {
  // پیش‌نمایش ممکن است هدر Authorization را رد کند؛ توکن از X-Auth-Token هم خوانده می‌شود
  const h = req.headers.authorization || '';
  const m = h.match(/^Bearer\s+(.+)$/i);
  return m ? m[1] : (req.headers['x-auth-token'] ? String(req.headers['x-auth-token']).trim() : '');
}
function currentUser(req) {
  const tok = userTokenOf(req);
  if (!tok) return null;
  const row = db.prepare(`SELECT u.id, u.phone, u.role, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?`).get(sha256(tok));
  if (!row) return null;
  if (row.expires_at < now()) { db.prepare('DELETE FROM sessions WHERE token_hash = ?').run(sha256(tok)); return null; }
  return row;
}
function requireUser(req, res, role) {
  const u = currentUser(req);
  if (!u) { send(res, 401, { error: 'unauthorized' }); return null; }
  if (role && u.role !== role) { send(res, 403, { error: 'forbidden_role' }); return null; }
  return u;
}

// ---------- مسیرهای API ----------
const routes = [];
const route = (method, pattern, handler) => {
  const keys = [];
  const re = new RegExp('^' + pattern.replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '$');
  routes.push({ method, pattern, re, keys, handler });
};

route('POST', '/api/auth/request-code', async (req, res) => {
  const ip = clientIp(req);
  const otpGate = RL.otpIp.check(ip);
  if (!otpGate.ok) return send(res, 429, { error: 'too_many_requests', retry_after: otpGate.retryAfter });
  RL.otpIp.fail(ip);
  const body = await readJson(req);
  const phone = normalizePhone(body.phone, body.role);
  if (!phone) return send(res, 400, { error: 'invalid_phone' });
  if (!ROLES.has(body.role)) return send(res, 400, { error: 'invalid_role' });
  const prev = db.prepare('SELECT created_at, locked_until FROM otp_codes WHERE phone = ? AND role = ?').get(phone, body.role);
  if (prev && prev.locked_until && prev.locked_until > now()) {
    return send(res, 423, { error: 'locked', retry_after: Math.ceil((prev.locked_until - now()) / 1000) });
  }
  if (prev && now() - prev.created_at < CONFIG.OTP_RESEND_SEC * 1000) {
    return send(res, 429, { error: 'resend_wait', retry_after: Math.ceil((prev.created_at + CONFIG.OTP_RESEND_SEC * 1000 - now()) / 1000) });
  }
  let code;
  if (DEV) code = CONFIG.DEV_CODE;
  else {
    if (!SMS.configured) return send(res, 503, { error: 'sms_provider_not_configured' });
    // کد تصادفی واقعی فقط وقتی ساخته و ارسال می‌شود که پیامک‌دهنده وصل باشد؛ اول ارسال، بعد ذخیره‌ی هش.
    code = String(crypto.randomInt(100000, 1000000));
    try { await SMS.send(phone, code); }
    catch (e) {
      console.error('[sms]', e && e.message ? e.message : e);
      return send(res, 503, { error: e && e.code === 'unsupported_phone' ? 'sms_unsupported_phone' : 'sms_send_failed' });
    }
  }
  db.prepare(`INSERT INTO otp_codes (phone, role, code_hash, expires_at, created_at, attempts, locked_until)
              VALUES (?, ?, ?, ?, ?, 0, NULL)
              ON CONFLICT(phone, role) DO UPDATE SET code_hash = excluded.code_hash, expires_at = excluded.expires_at,
              created_at = excluded.created_at, attempts = 0, locked_until = NULL`)
    .run(phone, body.role, sha256(phone + ':' + body.role + ':' + code), now() + CONFIG.OTP_TTL_SEC * 1000, now());
  send(res, 200, { ok: true, expires_in: CONFIG.OTP_TTL_SEC, resend_in: CONFIG.OTP_RESEND_SEC });
});

route('POST', '/api/auth/verify', async (req, res) => {
  const ip = clientIp(req);
  const vGate = RL.verifyFail.check(ip);
  if (!vGate.ok) return send(res, 429, { error: 'too_many_attempts', retry_after: vGate.retryAfter });
  const body = await readJson(req);
  const phone = normalizePhone(body.phone, body.role);
  if (!phone || !ROLES.has(body.role)) return send(res, 400, { error: 'invalid_input' });
  const code = String(body.code || '').replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace(/\D/g, '');
  const row = db.prepare('SELECT * FROM otp_codes WHERE phone = ? AND role = ?').get(phone, body.role);
  if (!row) return send(res, 400, { error: 'no_code_requested' });
  if (row.locked_until && row.locked_until > now()) return send(res, 423, { error: 'locked', retry_after: Math.ceil((row.locked_until - now()) / 1000) });
  if (row.expires_at < now()) return send(res, 410, { error: 'code_expired' });
  if (sha256(phone + ':' + body.role + ':' + code) !== row.code_hash) {
    const attempts = row.attempts + 1;
    if (attempts >= CONFIG.OTP_MAX_ATTEMPTS) {
      db.prepare('UPDATE otp_codes SET attempts = 0, locked_until = ? WHERE phone = ? AND role = ?').run(now() + CONFIG.OTP_LOCK_SEC * 1000, phone, body.role);
      return send(res, 423, { error: 'locked', retry_after: CONFIG.OTP_LOCK_SEC });
    }
    db.prepare('UPDATE otp_codes SET attempts = ? WHERE phone = ? AND role = ?').run(attempts, phone, body.role);
    RL.verifyFail.fail(ip);
    return send(res, 401, { error: 'wrong_code', attempts_left: CONFIG.OTP_MAX_ATTEMPTS - attempts });
  }
  db.prepare('DELETE FROM otp_codes WHERE phone = ? AND role = ?').run(phone, body.role);
  db.prepare('INSERT OR IGNORE INTO users (phone, role, created_at) VALUES (?, ?, ?)').run(phone, body.role, now());
  const user = db.prepare('SELECT id, phone, role FROM users WHERE phone = ? AND role = ?').get(phone, body.role);
  if (user.role === 'translator') db.prepare('INSERT OR IGNORE INTO translators (user_id, status, updated_at) VALUES (?, ?, ?)').run(user.id, 'registered', now());
  const token = randomToken();
  db.prepare('INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)').run(sha256(token), user.id, now() + CONFIG.SESSION_HOURS * 3600 * 1000);
  send(res, 200, { token, user: { id: user.id, role: user.role, phone: user.phone }, expires_in: CONFIG.SESSION_HOURS * 3600 });
});

// پرچم محیط: فقط برای نمایش دکمه‌ی آزمایشی در اپ مترجم. کد ثابت به کلاینت داده نمی‌شود.
route('GET', '/api/config', async (req, res) => {
  send(res, 200, { dev: DEV, payments: PAYMENTS, charter_text: getSetting('charter_text'),
    translator_terms_text: getSetting('translator_terms_text'), translator_nda_text: getSetting('translator_nda_text'),
    translator_help_text: getSetting('translator_help_text'), traveler_terms_text: getSetting('traveler_terms_text'), support_phone: getSetting('support_phone'),
    tariffs: { hourly: getJsonSetting('hourly_tariffs'), car_fee_per_hour: getSetting('car_fee_per_hour'),
      tax_percent: getSetting('tax_percent') },
    language_pairs: getJsonSetting('language_pairs').filter((x) => x.enabled),
    features: featuresNow(),
    cities: db.prepare('SELECT id, name_fa, name_en, lat, lng FROM cities WHERE traveler_enabled = 1 ORDER BY id').all(),
    translator_cities: db.prepare('SELECT id, name_fa, name_en FROM cities WHERE translator_enabled = 1 ORDER BY id').all(),
    default_city_id: defaultCityId() });
});

route('GET', '/api/auth/me', async (req, res) => {
  const u = requireUser(req, res);
  if (!u) return;
  send(res, 200, { id: u.id, role: u.role, phone: u.phone });
});

// Idempotent single-device logout; use the same header rules as authentication.
route('POST', '/api/auth/logout', async (req, res) => {
  const tok = userTokenOf(req);
  if (tok) db.prepare('DELETE FROM sessions WHERE token_hash = ?').run(sha256(tok));
  send(res, 200, { ok: true });
});

// Only the authenticated account may revoke its sessions. Never accept a target ID.
route('POST', '/api/auth/logout-all', async (req, res) => {
  const u = requireUser(req, res); if (!u) return;
  db.prepare('DELETE FROM sessions WHERE user_id = ?').run(u.id);
  send(res, 200, { ok: true });
});

// حذف حساب کاربر (مسافر یا مترجم): وقتی کارِ باز ندارد، حساب و داده‌هایش واقعاً از پایگاه داده پاک می‌شود.
// رزروِ باز یعنی در جستجو/تطبیق/تطبیق‌یافته، یا پایان‌یافته‌ای که هنوز تسویه نشده است؛ پیشنهادِ باز مترجم هم باز محسوب می‌شود.
// سابقه‌ی رزروهای تمام‌شده‌ی مترجمِ حذف‌شده بی‌نام نگه داشته می‌شود تا حساب‌وکتاب مالی به هم نریزد؛ نوبت مصاحبه‌ی گرفته‌شده آزاد می‌شود.
route('DELETE', '/api/auth/account', async (req, res) => {
  const u = requireUser(req, res); if (!u) return;
  const ACTIVE = "('searching','waiting_schedule','matching','unmatched_ask','matched')";
  const openAsTraveler = db.prepare(`SELECT COUNT(*) AS n FROM reservations WHERE traveler_id = ? AND (status IN ${ACTIVE} OR (status = 'finished' AND (pay_state IS NULL OR pay_state != 'settled')))`).get(u.id).n;
  const openAsTranslator = db.prepare(`SELECT COUNT(*) AS n FROM reservations WHERE translator_id = ? AND (status IN ${ACTIVE} OR (status = 'finished' AND (pay_state IS NULL OR pay_state != 'settled')))`).get(u.id).n;
  const openOffers = db.prepare("SELECT COUNT(*) AS n FROM offers WHERE translator_id = ? AND status = 'pending'").get(u.id).n;
  if (openAsTraveler + openAsTranslator + openOffers > 0) return send(res, 409, { error: 'active_items' });
  db.transaction(() => {
    db.prepare('UPDATE reservations SET translator_id = NULL WHERE translator_id = ?').run(u.id);
    db.prepare("UPDATE interview_slots SET booked_user_id = NULL, status = 'open' WHERE booked_user_id = ? AND status = 'booked'").run(u.id);
    db.prepare('DELETE FROM users WHERE id = ?').run(u.id);
  })();
  audit('account.delete', { role: u.role });
  send(res, 200, { ok: true });
});

route('GET', '/api/translator/status', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  const t = db.prepare('SELECT status FROM translators WHERE user_id = ?').get(u.id);
  send(res, 200, { status: t ? t.status : 'registered' });
});

// وضعیت چهار بُعد صلاحیت مترجم، از روی مدارک و ثبت‌نام واقعی (نه متن ثابت)
// نوبت‌های مصاحبه: فقط زمان‌های آزاد واقعی سامانه (سند ۵). مدیر نوبت می‌سازد.
route('GET', '/api/admin/interview-slots', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const rows = db.prepare(`SELECT s.id, s.starts_at, s.status, s.booked_user_id, u.phone AS phone
    FROM interview_slots s LEFT JOIN users u ON u.id = s.booked_user_id
    WHERE s.starts_at > ? OR s.status = 'booked' ORDER BY s.starts_at LIMIT 200`).all(now() - INTERVIEW_MIN * 60000);
  send(res, 200, { slots: rows.map((r) => ({ id: r.id, starts_at: new Date(r.starts_at).toISOString(), status: r.status, booked_user_id: r.booked_user_id, phone: r.phone || null })) });
});

route('POST', '/api/admin/interview-slots', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const b = await readJson(req);
  const at = typeof b.starts_at === 'string' || typeof b.starts_at === 'number' ? new Date(b.starts_at).getTime() : NaN;
  if (!Number.isFinite(at)) return send(res, 400, { error: 'invalid_time' });
  if (at <= now()) return send(res, 400, { error: 'time_in_past' });
  const note = typeof b.note === 'string' ? b.note.trim().slice(0, 300) : '';
  const r = db.prepare("INSERT INTO interview_slots (starts_at, status, created_at, note) VALUES (?, 'open', ?, ?)").run(at, now(), note);
  audit('interview.slot_create', { id: Number(r.lastInsertRowid) });
  send(res, 201, { ok: true, id: Number(r.lastInsertRowid) });
});

// عدم حضور: نوبت آزاد می‌شود و مترجم می‌تواند دوباره نوبت بگیرد (سند ۵)
route('POST', '/api/admin/interview-slots/:id/no-show', async (req, res, url, params) => {
  if (!requireAdmin(req, res)) return;
  const id = parseId(params.id);
  const sl = id && db.prepare("SELECT id, status FROM interview_slots WHERE id = ?").get(id);
  if (!sl) return send(res, 404, { error: 'not_found' });
  if (sl.status !== 'booked') return send(res, 409, { error: 'not_booked', status: sl.status });
  db.prepare("UPDATE interview_slots SET status = 'no_show' WHERE id = ?").run(id);
  send(res, 200, { ok: true, status: 'no_show' });
});

// مترجم: نوبت‌های آزاد و نوبت فعلی خودش
route('GET', '/api/translator/interview-slots', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  const t = now();
  const slots = db.prepare("SELECT id, starts_at FROM interview_slots WHERE status = 'open' AND starts_at > ? ORDER BY starts_at LIMIT 50").all(t);
  const mine = db.prepare("SELECT id, starts_at, note FROM interview_slots WHERE status = 'booked' AND booked_user_id = ? AND starts_at > ? ORDER BY starts_at LIMIT 1")
    .get(u.id, t - INTERVIEW_MIN * 60000);
  send(res, 200, { slots: slots.map((s) => ({ id: s.id, starts_at: new Date(s.starts_at).toISOString() })),
    booking: mine ? { id: mine.id, starts_at: new Date(mine.starts_at).toISOString(), note: mine.note || '' } : null });
});

route('POST', '/api/translator/interview-slots/:id/book', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!requireFeature(res, 'interview_scheduling')) return;
  const id = parseId(params.id);
  const t = db.prepare('SELECT langs, interview FROM translators WHERE user_id = ?').get(u.id);
  if (!t) return send(res, 404, { error: 'not_found' });
  if (JSON.parse(t.langs || '[]').length === 0) return send(res, 409, { error: 'languages_required' });
  if (t.interview === 'pass') return send(res, 409, { error: 'already_passed' });
  const mine = db.prepare("SELECT id FROM interview_slots WHERE status = 'booked' AND booked_user_id = ? AND starts_at > ?").get(u.id, now() - INTERVIEW_MIN * 60000);
  if (mine) return send(res, 409, { error: 'already_booked' });
  const sl = id && db.prepare('SELECT id, starts_at, status FROM interview_slots WHERE id = ?').get(id);
  if (!sl) return send(res, 404, { error: 'not_found' });
  if (sl.status !== 'open') return send(res, 409, { error: 'slot_taken' });
  if (sl.starts_at <= now()) return send(res, 409, { error: 'slot_past' });
  const r = db.prepare("UPDATE interview_slots SET status = 'booked', booked_user_id = ? WHERE id = ? AND status = 'open'").run(u.id, id);
  if (r.changes !== 1) return send(res, 409, { error: 'slot_taken' });
  send(res, 200, { ok: true, id, starts_at: new Date(sl.starts_at).toISOString() });
});

route('GET', '/api/translator/notifications', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  sweep();
  const rows = db.prepare(`SELECT n.id, n.kind, n.ref, n.created_at, d.kind AS doc_kind FROM translator_notifications n
    LEFT JOIN translator_documents d ON d.id = n.doc_id WHERE n.user_id = ? ORDER BY n.id DESC LIMIT 20`).all(u.id);
  send(res, 200, { notifications: rows.map((r) => ({ id: r.id, kind: r.kind, doc_kind: r.doc_kind,
    doc_name: DOC_NAME_FA[r.doc_kind] || r.doc_kind || '', created_at: new Date(r.created_at).toISOString(),
    text: r.kind === 'doc_rejected' ? 'مدرک «' + (DOC_NAME_FA[r.doc_kind] || r.doc_kind || '') + '» رد شد: ' + (r.ref || 'بدون دلیل') + '. مدرک اصلاح‌شده ارسال کنید.'
      : r.kind === 'expired' ? 'اعتبار مدرک شما تمام شده است؛ مدرک جدید ارسال کنید.'
      : r.kind === 'interview_reminder' ? 'یادآوری مصاحبه‌ی زبان: زمان و هماهنگی نوبت را در بخش مصاحبه ببینید.'
      : 'اعتبار مدرک شما ۳۰ روز دیگر یا کمتر تمام می‌شود.' })) });
});

route('GET', '/api/translator/capability', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  const t = db.prepare('SELECT status, langs, profile, interview FROM translators WHERE user_id = ?').get(u.id);
  if (!t) return send(res, 200, { status: 'registered', dimensions: null });
  const approved = new Set(db.prepare(`SELECT kind FROM translator_documents WHERE user_id = ? AND status = 'approved'
    AND (expires_at IS NULL OR expires_at >= ?)`).all(u.id, now()).map((r) => r.kind));
  const profile = JSON.parse(t.profile || '{}');
  const IDENTITY = ['nid_card', 'selfie', 'address_proof', 'drug_free', 'criminal_record'];
  const identityMissing = IDENTITY.filter((k) => !approved.has(k));
  const langsOk = JSON.parse(t.langs || '[]').length > 0 && !['registered', 'in_progress'].includes(t.status);
  send(res, 200, { status: t.status, dimensions: {
    identity: { ok: identityMissing.length === 0, missing: identityMissing },
    language: { ok: langsOk && t.interview === 'pass', langs: JSON.parse(t.langs || '[]'), interview: t.interview || null },
    car: { registered: profile.car === true, active: carReady(t, 1) },
    medical: { ok: true, permit_required: false },
  } });
});

// فقط در حالت توسعه: همه‌ی مترجمان آفلاین شوند تا تست‌ها به مترجم‌های باقی‌مانده وابسته نباشند
route('POST', '/api/dev/offline-all', async (req, res) => {
  if (!DEV) return send(res, 404, { error: 'not_found' });
  db.prepare('UPDATE translators SET online = 0').run();
  // رزروهای جستجوی باقی‌مانده از تست‌های قبلی هم بسته شوند تا پیشنهادها را ندزدند
  db.prepare("UPDATE reservations SET status = 'cancelled', updated_at = ? WHERE status IN ('searching','waiting_schedule','matching','unmatched_ask','no_match')").run(now());
  db.prepare("UPDATE offers SET status = 'expired', decided_at = ? WHERE status = 'pending'").run(now());
  send(res, 200, { ok: true });
});

// فقط در حالت توسعه: شبیه‌سازی تأیید کارشناس انسانی (سند ۷.۳)
// فقط حالت توسعه: همه‌ی مدارک این مترجم را منقضی می‌کند (برای تست خاموش شدن حالت خودرو)
route('POST', '/api/dev/expire-docs', async (req, res) => {
  if (!DEV) return send(res, 404, { error: 'not_found' });
  const u = requireUser(req, res, 'translator'); if (!u) return;
  db.prepare('UPDATE translator_documents SET expires_at = ? WHERE user_id = ?').run(now() - DAY_MS, u.id);
  send(res, 200, { ok: true });
});

route('POST', '/api/dev/approve-translator', async (req, res) => {
  if (!DEV) return send(res, 404, { error: 'not_found' });
  const u = requireUser(req, res, 'translator'); if (!u) return;
  // فقط در حالت توسعه: مترجم آزمایشی همه‌ی زمینه‌ها را دارد تا تست‌های قبلی معنا داشته باشند
  db.prepare(`INSERT INTO translators (user_id, status, fields, interview, updated_at) VALUES (?, 'active_general', '["general","medical","legal","business"]', 'pass', ?)
              ON CONFLICT(user_id) DO UPDATE SET status = 'active_general', fields = excluded.fields, interview = 'pass', updated_at = excluded.updated_at`).run(u.id, now());
  db.prepare('UPDATE translators SET city_id = COALESCE(city_id, ?) WHERE user_id = ?').run(defaultCityId(), u.id);
  send(res, 200, { status: 'active_general' });
});


// فقط در حالت توسعه: افزودن ماموریت آزمایشی برای مترجم فعال
route('POST', '/api/dev/missions', async (req, res) => {
  if (!DEV) return send(res, 404, { error: 'not_found' });
  const u = requireUser(req, res, 'translator'); if (!u) return;
  const b = await readJson(req);
  const startAt = Date.parse(b.startAt);
  if (!b.code || !Number.isFinite(startAt)) return send(res, 400, { error: 'invalid_mission' });
  const info = db.prepare(`INSERT INTO missions (translator_id, code, purpose, traveler_name, place, start_at, total, net, status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .run(u.id, String(b.code), String(b.purpose || ''), String(b.travelerName || ''), String(b.place || ''), startAt,
      Number(b.total || 0), Number(b.net || 0), b.status === 'pending_invite' ? 'pending_invite' : 'accepted');
  send(res, 201, { id: info.lastInsertRowid });
});



// ---------- فایل‌های استاتیک ----------
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.map': 'application/json' };

function serveStatic(req, res, pathname) {
  for (const prefix of Object.keys(STATIC_ROOTS)) {
    if (!pathname.startsWith(prefix)) continue;
    let rel = decodeURIComponent(pathname.slice(prefix.length));
    if (rel === '' || rel.endsWith('/')) rel += 'index.html';
    const root = STATIC_ROOTS[prefix];
    const file = path.normalize(path.join(root, rel));
    if (!file.startsWith(root + path.sep)) { res.writeHead(403); return res.end('forbidden'); }
    fs.stat(file, (err, st) => {
      if (err || !st.isFile()) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); return res.end('not found'); }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
      fs.createReadStream(file).pipe(res);
    });
    return;
  }
  if (pathname === '/') {
    const page = `<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>همراه — انتخاب بخش</title>
<style>body{font-family:system-ui,sans-serif;background:#eef2f6;margin:0;padding:24px;color:#161c23}h1{font-size:20px}
.g{display:grid;gap:12px;max-width:420px}a{display:block;padding:16px;border-radius:14px;background:#006a61;color:#fff;text-decoration:none;font-weight:bold}
a.s{background:#005182}p{font-size:13px;color:#555}</style></head><body>
<h1>همراه — انتخاب بخش</h1>
<div class="g">
<a href="/traveler/index.html">اپ مسافر</a>
<a class="s" href="/translator/index.html">اپ مترجم</a>
<a href="/admin/index.html">پنل مدیر</a>
</div>
<p>پنل مدیر فقط از طریق همین سرور باز می‌شود.</p>
</body></html>`;
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); return res.end(page);
  }
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end('not found');
}

// ---------- سرور ----------
// ---------- زمان‌بندی و مبالغ (مقدار نمونه؛ تعرفه و مهلت‌ها در پنل مدیریت تعیین می‌شوند) ----------
const SCALE = Number(process.env.HZ_TIME_SCALE) || 1; // فقط برای تست سریع (مثلاً 0.01)
const TIMING = {
  OFFER_MS: 60 * 1000 * SCALE,                    // مهلت پذیرش مترجم
  INSTANT_SEARCH_MS: 10 * 60 * 1000 * SCALE,      // سقف جستجوی فوری
  SCHEDULE_MIN_LEAD_MS: 2 * 3600 * 1000 * SCALE,  // حداقل فاصله‌ی رزرو زمان‌دار تا قرار
  SCHEDULE_MATCH_BEFORE_MS: 60 * 60 * 1000 * SCALE, // شروع تطبیق یک ساعت قبل
  SCHEDULE_ASK_BEFORE_MS: 15 * 60 * 1000 * SCALE,   // پرسش «تلاش دوباره یا لغو؟»
};
// ---------- تنظیمات قابل تغییر (پنل ادمین) ----------
// فقط مقادیری که مدیر به‌طور منظم تغییر می‌دهد اینجا هستند. مقادیر ثابت (مثل مهلت‌های ۶۰ ثانیه و ۱۰ دقیقه) در کد می‌مانند.
const SETTING_DEFS = {
  translator_share_percent: { v: 80, type: 'int', min: 0, max: 100, label: 'سهم مترجم از خدمت (٪)' },
  cancel_fee_percent: { v: 20, type: 'int', min: 0, max: 100, label: 'کارمزد لغو بعد از تطبیق (٪)' },
  tax_percent: { v: 0, type: 'int', min: 0, max: 100, label: 'نرخ مالیات (٪) — هنوز تعیین نشده' },
  cash_enabled: { v: 1, type: 'bool', label: 'پرداخت نقدی فعال باشد' },
  online_enabled: { v: 0, type: 'bool', label: 'پرداخت آنلاین فعال باشد (درگاه هنوز وصل نیست)' },
  default_city_id: { v: 1, type: 'int', min: 1, max: 1000000000, label: 'شهر پیش‌فرض (وقتی اپ شهری نمی‌فرستد)' },
  settlement_period: { v: 'daily', type: 'enum', values: ['daily', 'weekly'], label: 'دوره‌ی تسویه با شبا' },
  translator_terms_text: { v: '', type: 'text', max: 20000, label: 'متن شرایط همکاری مترجم (گام ۱)' },
  translator_nda_text: { v: '', type: 'text', max: 20000, label: 'متن تعهدنامه‌ی محرمانگی (NDA) مترجم (گام ۵)' },
  charter_text: { v: '', type: 'text', max: 20000, label: 'متن منشور اخلاقی مترجم (گام ۵، ضمیمه‌ی تعهدنامه)' },
  translator_help_text: { v: '', type: 'text', max: 20000, label: 'متن راهنمای مترجم (دکمه‌ی راهنما و پشتیبانی)' },
  support_phone: { v: '', type: 'text', max: 100, label: 'شماره‌ی تلفن پشتیبانی (مسافر و مترجم)' },
  traveler_terms_text: { v: '', type: 'text', max: 20000, label: 'متن قوانین و ضوابط همراهی تشریفاتی (اپ مسافر)' },
  car_fee_per_hour: { v: 350000, type: 'int', min: 0, max: 100000000000, label: 'هزینه‌ی خودرو در هر ساعت (تومان)' },
  hourly_tariffs: { v: '{"general":1450000,"medical":1685000,"business":1950000,"tourism":1350000}', type: 'json', max: 2000,
    label: 'تعرفه‌ی ساعتی هر دسته (تومان): general, medical, business, tourism',
    validate: (o) => {
      if (!o || typeof o !== 'object' || Array.isArray(o)) return null;
      const out = {};
      for (const k of ['general', 'medical', 'business', 'tourism']) {
        const n = Number(o[k]);
        if (!Number.isInteger(n) || n < 0 || n > 1e11) return null;
        out[k] = n;
      }
      return out;
    } },
  language_pairs: { v: '[{"code":"ar-fa","label":"عربی ⟷ فارسی","note":"خلیجی، عراقی و فصیح","langs":["ar","fa"],"enabled":true},{"code":"en-fa","label":"انگلیسی ⟷ فارسی","note":"مکالمه‌ی تخصصی و اداری","langs":["en","fa"],"enabled":true},{"code":"tr-fa","label":"ترکی استانبولی ⟷ فارسی","note":"","langs":["tr","fa"],"enabled":true},{"code":"fr-fa","label":"فرانسوی ⟷ فارسی","note":"","langs":["fr","fa"],"enabled":true},{"code":"ru-fa","label":"روسی ⟷ فارسی","note":"","langs":["ru","fa"],"enabled":true},{"code":"zh-fa","label":"چینی ماندارین ⟷ فارسی","note":"","langs":["zh","fa"],"enabled":true}]', type: 'json', max: 20000,
    label: 'جفت‌زبان‌های ثبت‌نام مترجم (کد، برچسب، توضیح، دو زبان، فعال یا غیرفعال)',
    validate: (a) => {
      if (!Array.isArray(a) || a.length < 1 || a.length > 12) return null;
      const seen = new Set(); const out = [];
      for (const x of a) {
        if (!x || typeof x !== 'object') return null;
        const code = String(x.code || '').trim();
        const label = String(x.label || '').trim();
        const note = String(x.note || '').trim();
        if (!/^[a-z]{2}-[a-z]{2}$/.test(code) || seen.has(code) || !label || label.length > 60 || note.length > 120) return null;
        if (!Array.isArray(x.langs) || x.langs.length !== 2 || x.langs[0] === x.langs[1]) return null;
        if (!x.langs.every((l) => LANG_CODES.includes(l))) return null;
        if (typeof x.enabled !== 'boolean') return null;
        seen.add(code);
        out.push({ code, label, note, langs: x.langs.slice(), enabled: x.enabled });
      }
      return out;
    } },
};
const LANG_CODES = ['fa', 'ar', 'en', 'tr', 'fr', 'ru', 'zh'];
function settingRaw(key) {
  const row = db.prepare('SELECT value FROM settings WHERE key = ?').get(key);
  return row ? row.value : null;
}
function getSetting(key) {
  const def = SETTING_DEFS[key];
  const raw = settingRaw(key);
  if (raw === null) return def.v;
  if (def.type === 'int') return Number(raw);
  if (def.type === 'bool') return raw === '1';
  return raw;
}
function getJsonSetting(key) {
  try { return JSON.parse(getSetting(key)); } catch (e) { return JSON.parse(SETTING_DEFS[key].v); }
}
// validate returns normalized string value or null
function normalizeSetting(key, value) {
  const def = SETTING_DEFS[key];
  if (!def) return null;
  if (def.type === 'int') {
    const n = Number(value);
    if (!Number.isInteger(n) || n < def.min || n > def.max) return null;
    return String(n);
  }
  if (def.type === 'bool') return value === true || value === 1 || value === '1' ? '1' : (value === false || value === 0 || value === '0' ? '0' : null);
  if (def.type === 'enum') return def.values.includes(value) ? String(value) : null;
  if (def.type === 'text') return typeof value === 'string' && value.length <= def.max ? value : null;
  if (def.type === 'json') {
    let o = value;
    if (typeof value === 'string') { try { o = JSON.parse(value); } catch (e) { return null; } }
    const norm = def.validate(o);
    if (norm === null) return null;
    const txt = JSON.stringify(norm);
    return txt.length <= def.max ? txt : null;
  }
  return null;
}

// مقادیر پویا: همیشه از پایگاه داده خوانده می‌شوند تا تغییر مدیر فوراً اعمال شود
const PRICING = {
  get TRANSLATOR_SHARE() { return getSetting('translator_share_percent') / 100; },
  get CANCEL_FEE_PERCENT() { return getSetting('cancel_fee_percent'); },
  get TAX_PERCENT() { return getSetting('tax_percent'); },
};
const PAYMENTS = {
  get CASH() { return getSetting('cash_enabled'); },
  get ONLINE() { return getSetting('online_enabled'); },
};

// ---------- ورود مدیر ----------
// رمز آغازین مدیر از متغیر محیطی HZ_ADMIN_PASSWORD خوانده می‌شود؛ اگر تنظیم نشده باشد، پنل بسته است.
// مدیر می‌تواند بعداً از داخل پنل رمز را عوض کند؛ در آن صورت هش ذخیره‌شده در پایگاه داده معتبر است و بر مقدار محیطی مقدم می‌شود.
const ADMIN_PASSWORD = process.env.HZ_ADMIN_PASSWORD || '';
function hashAdminPassword(pw) {
  const salt = crypto.randomBytes(16).toString('hex');
  return 'scrypt:' + salt + ':' + crypto.scryptSync(String(pw), salt, 64).toString('hex');
}
function verifyAdminPassword(pw) {
  const stored = settingRaw('admin_password_hash');
  if (stored) {
    const parts = String(stored).split(':');
    if (parts.length !== 3 || parts[0] !== 'scrypt') return false;
    const given = crypto.scryptSync(String(pw || ''), parts[1], 64);
    const want = Buffer.from(parts[2], 'hex');
    return given.length === want.length && crypto.timingSafeEqual(given, want);
  }
  if (!ADMIN_PASSWORD) return false;
  const given = crypto.createHash('sha256').update(String(pw || '')).digest();
  const want = crypto.createHash('sha256').update(ADMIN_PASSWORD).digest();
  return crypto.timingSafeEqual(given, want);
}
// محدودکننده‌ی تلاش: فقط شکست‌ها شمرده می‌شوند (ضد حدس رمز و کد)
const RL = {
  adminFail: makeLimiter({ max: Number(process.env.HZ_RL_ADMIN_MAX) || 10, windowMs: 15 * 60 * 1000 }),
  otpIp: makeLimiter({ max: Number(process.env.HZ_RL_OTP_MAX) || 300, windowMs: 10 * 60 * 1000 }),
  verifyFail: makeLimiter({ max: Number(process.env.HZ_RL_VERIFY_MAX) || 100, windowMs: 10 * 60 * 1000 }),
};
const FRAME_ANCESTORS = process.env.HZ_FRAME_ANCESTORS || "'self' https://*.e2b.app";
const ADMIN_SESSION_MS = 8 * 3600 * 1000;
// نشانهٔ مدیر از سرصفحه‌ی Authorization یا X-Admin-Token خوانده می‌شود (برخی واسطه‌ها Authorization را حذف می‌کنند)
function adminTokenOf(req) {
  const m = (req.headers.authorization || '').match(/^Bearer\s+(.+)$/i);
  if (m) return m[1];
  const x = req.headers['x-admin-token'];
  return typeof x === 'string' && x ? x : null;
}
function adminOf(req) {
  const tok = adminTokenOf(req);
  if (!tok) return false;
  const row = db.prepare('SELECT expires_at FROM admin_sessions WHERE token_hash = ?').get(sha256(tok));
  if (!row) return false;
  if (row.expires_at < now()) { db.prepare('DELETE FROM admin_sessions WHERE token_hash = ?').run(sha256(tok)); return false; }
  return true;
}
function requireAdmin(req, res) {
  if (!ADMIN_PASSWORD) { send(res, 404, { error: 'not_found' }); return false; }
  if (!adminOf(req)) { send(res, 401, { error: 'unauthorized' }); return false; }
  return true;
}

route('POST', '/api/admin/login', async (req, res) => {
  if (!ADMIN_PASSWORD) return send(res, 404, { error: 'not_found' });
  const ip = clientIp(req);
  const gate = RL.adminFail.check(ip);
  if (!gate.ok) return send(res, 429, { error: 'too_many_attempts', retry_after: gate.retryAfter });
  const b = await readJson(req);
  if (!verifyAdminPassword(b.password)) { RL.adminFail.fail(ip); return send(res, 401, { error: 'bad_password' }); }
  RL.adminFail.reset(ip);
  const token = crypto.randomBytes(32).toString('hex');
  db.prepare('INSERT INTO admin_sessions (token_hash, expires_at) VALUES (?, ?)').run(sha256(token), now() + ADMIN_SESSION_MS);
  send(res, 200, { token, expires_in: ADMIN_SESSION_MS / 1000 });
});

route('POST', '/api/admin/logout', async (req, res) => {
  const tok = adminTokenOf(req);
  if (tok) db.prepare('DELETE FROM admin_sessions WHERE token_hash = ?').run(sha256(tok));
  send(res, 200, { ok: true });
});

// تغییر رمز مدیر از داخل پنل: رمز فعلی لازم است، رمز تازه حداقل ۱۲ کاراکتر و غیرآزمایشی.
// هش رمز تازه (scrypt) در پایگاه داده ذخیره می‌شود و از آن پس بر رمز محیطی مقدم است.
// نشست‌های دیگر مدیر باطل می‌شوند؛ نشست فعلی می‌ماند. خودِ رمز هیچ‌جا ثبت نمی‌شود.
route('POST', '/api/admin/change-password', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const b = await readJson(req);
  if (!verifyAdminPassword(b.current_password)) return send(res, 401, { error: 'bad_current_password' });
  const next = String(b.new_password || '');
  if (isWeakAdminPassword(next)) return send(res, 400, { error: 'weak_password' });
  db.prepare('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value')
    .run('admin_password_hash', hashAdminPassword(next));
  db.prepare('DELETE FROM admin_sessions WHERE token_hash != ?').run(sha256(adminTokenOf(req) || ''));
  audit('admin.change_password', {});
  send(res, 200, { ok: true });
});

route('GET', '/api/admin/settings', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const out = {};
  for (const k of Object.keys(SETTING_DEFS)) {
    const d = SETTING_DEFS[k];
    out[k] = { value: getSetting(k), type: d.type, label: d.label, values: d.values || null, min: d.min ?? null, max: d.max ?? null };
  }
  send(res, 200, { settings: out });
});

route('PUT', '/api/admin/settings', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const b = await readJson(req);
  const keys = Object.keys(b || {});
  if (!keys.length) return send(res, 400, { error: 'nothing_to_change' });
  const rows = [];
  for (const k of keys) {
    if (!SETTING_DEFS[k]) return send(res, 400, { error: 'unknown_key', key: k });
    const v = normalizeSetting(k, b[k]);
    if (v === null) return send(res, 400, { error: 'invalid_value', key: k });
    if (k === 'default_city_id') {
      const c = db.prepare('SELECT traveler_enabled FROM cities WHERE id = ?').get(Number(v));
      if (!c || !c.traveler_enabled) return send(res, 400, { error: 'invalid_city', key: k });
    }
    rows.push([k, v]);
  }
  db.transaction(() => {
    for (const [k, v] of rows) db.prepare('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value').run(k, v);
  })();
  audit('settings.update', { keys });
  send(res, 200, { ok: true, changed: keys });
});

route('GET', '/api/admin/summary', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const reservations = {};
  for (const r of db.prepare('SELECT status, COUNT(*) AS n FROM reservations GROUP BY status').all()) reservations[r.status] = r.n;
  const translators = {};
  for (const r of db.prepare('SELECT status, COUNT(*) AS n FROM translators GROUP BY status').all()) translators[r.status] = r.n;
  const payments_waiting = db.prepare("SELECT COUNT(*) AS n FROM reservations WHERE status = 'finished' AND (pay_state IS NULL OR pay_state != 'settled')").get().n;
  const disputes = db.prepare("SELECT COUNT(*) AS n FROM reservations WHERE pay_state = 'disputed'").get().n;
  send(res, 200, { reservations, translators, payments_waiting, disputes });
});

// کدهای امنیتی قفل‌شده (۵ تلاش ناموفق): مدیر می‌تواند قفل را باز کند یا کد تازه بسازد. خود کد هرگز به پنل داده نمی‌شود.
route('GET', '/api/admin/locked-service-codes', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const rows = db.prepare(`SELECT id, traveler_name, place, status, service_code_attempts, created_at
    FROM reservations WHERE service_code_attempts >= 5 AND status = 'matched' ORDER BY created_at DESC LIMIT 100`).all();
  send(res, 200, { locked: rows.map((r) => ({ id: r.id, traveler_name: r.traveler_name || '', place: r.place || '',
    status: r.status, attempts: r.service_code_attempts, created_at: r.created_at })) });
});

route('POST', '/api/admin/reservations/:id/unlock-service-code', async (req, res, url, params) => {
  if (!requireAdmin(req, res)) return;
  const id = parseId(params.id);
  const r = id && db.prepare('SELECT id FROM reservations WHERE id = ?').get(id);
  if (!r) return send(res, 404, { error: 'not_found' });
  const b = await readJson(req).catch(() => ({}));
  if (b && b.regenerate === true) {
    const fresh = String(crypto.randomInt(10000, 100000));
    db.prepare('UPDATE reservations SET service_code = ?, service_code_attempts = 0, updated_at = ? WHERE id = ?')
      .run(encryptServiceCode(fresh), now(), r.id);
    return send(res, 200, { ok: true, regenerated: true });
  }
  db.prepare('UPDATE reservations SET service_code_attempts = 0, updated_at = ? WHERE id = ?').run(now(), r.id);
  send(res, 200, { ok: true, regenerated: false });
});

route('GET', '/api/admin/translators', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const q = new URL(req.url, 'http://x').searchParams;
  const status = q.get('status') || 'pending_review';
  const limit = Math.min(Math.max(parseInt(q.get('limit'), 10) || 50, 1), 200);
  const offset = Math.max(parseInt(q.get('offset'), 10) || 0, 0);
  // جستجو روی شماره و نام (نام در پروفایل ذخیره شده است)؛ نویسه‌های LIKE escape می‌شوند
  const term = String(q.get('q') || '').trim().slice(0, 60).replace(/[\\%_]/g, (c) => '\\' + c);
  const where = 't.status = ?' + (term ? " AND (u.phone LIKE ? ESCAPE '\\' OR (COALESCE(json_extract(t.profile, '$.first_name'), '') || ' ' || COALESCE(json_extract(t.profile, '$.last_name'), '')) LIKE ? ESCAPE '\\')" : '');
  const params = term ? [status, `%${term}%`, `%${term}%`] : [status];
  const total = db.prepare(`SELECT COUNT(*) AS n FROM translators t JOIN users u ON u.id = t.user_id WHERE ${where}`).get(...params).n;
  const rows = db.prepare(`SELECT t.user_id AS id, u.phone, t.status, t.gender, t.score, t.updated_at, t.profile FROM translators t
      JOIN users u ON u.id = t.user_id WHERE ${where} ORDER BY t.updated_at, t.user_id LIMIT ? OFFSET ?`).all(...params, limit, offset)
    .map((r) => {
      let pr = {}; try { pr = JSON.parse(r.profile || '{}'); } catch (e) {}
      return { id: r.id, phone: r.phone, status: r.status, gender: r.gender, score: r.score, updated_at: r.updated_at,
        name: [pr.first_name, pr.last_name].filter(Boolean).join(' ') };
    });
  send(res, 200, { translators: rows, total, limit, offset });
});

// تصمیم کارشناس انسانی: فقط از وضعیت «در انتظار بررسی نهایی» (سند ۷.۳)
route('POST', '/api/admin/translators/:id/decision', async (req, res, url, params) => {
  if (!requireAdmin(req, res)) return;
  const id = parseId(params.id);
  const b = await readJson(req);
  const t = id && db.prepare('SELECT status FROM translators WHERE user_id = ?').get(id);
  if (!t) return send(res, 404, { error: 'not_found' });
  if (t.status !== 'pending_review') return send(res, 409, { error: 'not_pending_review', status: t.status });
  const next = b.decision === 'approve' ? 'active_general' : b.decision === 'reject' ? 'rejected' : null;
  if (!next) return send(res, 400, { error: 'invalid_decision' });
  db.prepare('UPDATE translators SET status = ?, updated_at = ? WHERE user_id = ?').run(next, now(), id);
  send(res, 200, { ok: true, status: next });
});

// فهرست مدارک در انتظار بررسی؛ محتوا فقط با درخواست صریح باز می‌شود
// هر مترجم یک ردیف: همه‌ی مدارک فعالش با وضعیت هرکدام (مدارک جایگزین‌شده نمایش داده نمی‌شوند)
route('GET', '/api/admin/translator-docs', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const q = new URL(req.url, 'http://x').searchParams;
  const onlyReview = q.get('filter') !== 'all';
  const limit = Math.min(Math.max(parseInt(q.get('limit'), 10) || 50, 1), 200);
  const offset = Math.max(parseInt(q.get('offset'), 10) || 0, 0);
  const cond = onlyReview ? "AND EXISTS (SELECT 1 FROM translator_documents d WHERE d.user_id = t.user_id AND d.status = 'uploaded')" : '';
  const total = db.prepare(`SELECT COUNT(*) AS n FROM translators t WHERE 1=1 ${cond}`).get().n;
  const people = db.prepare(`SELECT t.user_id AS id, u.phone, t.status, t.profile FROM translators t
    JOIN users u ON u.id = t.user_id WHERE 1=1 ${cond} ORDER BY t.user_id DESC LIMIT ? OFFSET ?`).all(limit, offset);
  if (!people.length) return send(res, 200, { translators: [], total, limit, offset });
  const ids = people.map((p) => p.id);
  const docs = db.prepare(`SELECT id, user_id, kind, status, mime, size, reject_reason, expires_at, updated_at FROM translator_documents
    WHERE user_id IN (${ids.map(() => '?').join(',')}) AND status != 'superseded' ORDER BY kind, id`).all(...ids);
  const byUser = new Map();
  const tNow = now();
  for (const d of docs) {
    if (!byUser.has(d.user_id)) byUser.set(d.user_id, []);
    byUser.get(d.user_id).push({ id: d.id, kind: d.kind, status: d.status, mime: d.mime, size: d.size,
      reject_reason: d.reject_reason || '', expires_at: d.expires_at ? new Date(d.expires_at).toISOString() : null,
      expired: !!d.expires_at && d.expires_at < tNow, updated_at: new Date(d.updated_at).toISOString() });
  }
  send(res, 200, { translators: people.map((p) => {
    let pr = {}; try { pr = JSON.parse(p.profile || '{}'); } catch (e) {}
    return { id: p.id, phone: p.phone, status: p.status, name: [pr.first_name, pr.last_name].filter(Boolean).join(' '),
      documents: byUser.get(p.id) || [] };
  }), total, limit, offset });
});

route('GET', '/api/admin/documents', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const status = new URL(req.url, 'http://x').searchParams.get('status') || 'uploaded';
  if (!['uploaded', 'approved', 'rejected'].includes(status)) return send(res, 400, { error: 'invalid_status' });
  const rows = db.prepare(`SELECT d.id, d.user_id, u.phone, d.kind, d.status, d.mime, d.size, d.reject_reason, d.expires_at, d.updated_at
    FROM translator_documents d JOIN users u ON u.id = d.user_id WHERE d.status = ? ORDER BY d.updated_at LIMIT 200`).all(status);
  const expiresIso = (r) => (r.expires_at ? new Date(r.expires_at).toISOString() : null);
  send(res, 200, { documents: rows.map((r) => ({ ...r, expires_at: expiresIso(r), expired: !!r.expires_at && r.expires_at < now(), updated_at: new Date(r.updated_at).toISOString() })) });
});

route('GET', '/api/admin/documents/:id/file', async (req, res, url, params) => {
  if (!requireAdmin(req, res)) return;
  const id = parseId(params.id);
  const row = id && db.prepare('SELECT mime, blob FROM translator_documents WHERE id = ?').get(id);
  if (!row) return send(res, 404, { error: 'not_found' });
  const buf = decryptDoc(row.blob);
  audit('document.view', { id });
  send(res, 200, { mime: row.mime, data: `data:${row.mime};base64,${buf.toString('base64')}` });
});

route('POST', '/api/admin/documents/:id/decision', async (req, res, url, params) => {
  if (!requireAdmin(req, res)) return;
  const id = parseId(params.id);
  const b = await readJson(req);
  const d = id && db.prepare('SELECT id, user_id, kind, expires_at FROM translator_documents WHERE id = ?').get(id);
  if (!d) return send(res, 404, { error: 'not_found' });
  if (b.decision === 'approve') {
    if (d.expires_at && d.expires_at < now()) return send(res, 409, { error: 'doc_expired' });
    db.prepare(`UPDATE translator_documents SET status = 'superseded', updated_at = ? WHERE user_id = ? AND kind = ? AND status = 'approved' AND id != ?`).run(now(), d.user_id, d.kind, id);
    db.prepare(`UPDATE translator_documents SET status = 'approved', reject_reason = NULL, updated_at = ? WHERE id = ?`).run(now(), id);
  } else if (b.decision === 'reject') {
    const reason = clip(b.reason, 200);
    if (!reason) return send(res, 400, { error: 'reason_required' });
    db.prepare(`UPDATE translator_documents SET status = 'rejected', reject_reason = ?, updated_at = ? WHERE id = ?`).run(reason, now(), id);
    db.prepare(`INSERT OR IGNORE INTO translator_notifications (user_id, doc_id, kind, created_at, ref) VALUES (?, ?, 'doc_rejected', ?, ?)`).run(d.user_id, id, now(), reason);
  } else return send(res, 400, { error: 'invalid_decision' });
  audit('document.' + b.decision, { id, reason: b.decision === 'reject' ? clip(b.reason, 200) : undefined });
  send(res, 200, { ok: true });
});

// نتیجه‌ی مصاحبه‌ی زبان (کارشناس انسانی): «pass» یا «retry». هر تلاش در تاریخچه ثبت می‌شود (سند ۵).
route('POST', '/api/admin/translators/:id/interview', async (req, res, url, params) => {
  if (!requireAdmin(req, res)) return;
  const id = parseId(params.id);
  const b = await readJson(req);
  const t = id && db.prepare('SELECT status FROM translators WHERE user_id = ?').get(id);
  if (!t) return send(res, 404, { error: 'not_found' });
  if (REG_CLOSED.has(t.status)) return send(res, 409, { error: 'registration_closed', status: t.status });
  if (b.result !== 'pass' && b.result !== 'retry') return send(res, 400, { error: 'invalid_result' });
  db.prepare('UPDATE translators SET interview = ?, updated_at = ? WHERE user_id = ?').run(b.result, now(), id);
  db.prepare('INSERT INTO translator_interviews (user_id, result, created_at) VALUES (?, ?, ?)').run(id, b.result, now());
  send(res, 200, { ok: true, result: b.result });
});

const LANGS = new Set(LANG_CODES);
const FIELDS = new Set(['general', 'medical', 'legal', 'business']);
const GENDER_PREF = new Set(['any', 'female', 'male']); // ترجیح جنسیت مترجم (دکمه‌های اپ مسافر)
const SEARCHABLE = ['searching', 'matching'];
const CANCELLABLE = ['searching', 'waiting_schedule', 'matching', 'unmatched_ask', 'no_match'];

const setStatus = (id, status) => db.prepare('UPDATE reservations SET status = ?, updated_at = ? WHERE id = ?').run(status, now(), id);
const closeOffers = (rid, status = 'withdrawn') =>
  db.prepare("UPDATE offers SET status = ?, decided_at = ? WHERE reservation_id = ? AND status = 'pending'").run(status, now(), rid);

// مترجم‌های آنلاین، فعال، با هر دو زبان؛ کسی که قبلاً پیشنهاد گرفته یا پیشنهاد باز دارد، دوباره نمی‌گیرد
// ترجیح مسافر: «خانم/آقا» یعنی فقط مترجم همان جنسیت؛ «فرقی‌ندارد» یعنی هم‌جنس مسافر، یا مترجمی که پذیرش هر جنسیت را دارد
function genderOk(r, t) {
  if (r.gender_pref === 'female' || r.gender_pref === 'male') return t.gender === r.gender_pref;
  if (!r.traveler_gender) return true;
  const same = t.gender && t.gender === r.traveler_gender;
  return !!same || !!t.accept_any;
}
// مترجم در بازه‌ی ±۲ ساعت ماموریت دیگری ندارد
function busyAt(translatorId, startMs, exceptId) {
  return !!db.prepare(`SELECT 1 FROM reservations WHERE translator_id = ? AND status = 'matched' AND id != ?
      AND ABS(COALESCE(scheduled_at, matched_at) - ?) < ?`).get(translatorId, exceptId || 0, startMs, 2 * 3600 * 1000);
}
const startOf = (r) => r.scheduled_at || now();

// همراهی با خودرو فقط وقتی: مترجم خودرو ثبت کرده، و مدارک خودرو و گواهینامه‌اش تأیید شده‌اند (سند ۶.۲).
// مترجم دیگر فقط مأموریت پیاده می‌بیند؛ مأموریت سواره برای او پنهان است.
function carReady(t, party) {
  const p = JSON.parse(t.profile || '{}');
  if (p.car !== true) return false;
  // ظرفیت خودرو باید حداقل به تعداد مسافران باشد (سند ۶.۲)
  if (!p.car_capacity || p.car_capacity < (Number(party) || 1)) return false;
  // انقضا همین لحظه بررسی می‌شود: مدرک منقضی‌شده، حالت خودرو را خاموش می‌کند
  const ok = db.prepare(`SELECT COUNT(*) AS n FROM translator_documents WHERE user_id = ? AND status = 'approved'
    AND kind IN ('car_docs', 'licence') AND (expires_at IS NULL OR expires_at >= ?)`).get(t.user_id, now());
  return ok.n === 2;
}

function eligibleTranslators(r) {
  if (!featureOn('translator_online')) return [];
  const rows = db.prepare(`SELECT t.user_id, t.langs, t.fields, t.profile, t.gender, t.accept_any FROM translators t
    JOIN cities c ON c.id = t.city_id AND c.translator_enabled = 1
    WHERE t.city_id = ? AND t.online = 1 AND t.status LIKE 'active_%' AND t.interview = 'pass'
      AND NOT EXISTS (SELECT 1 FROM offers o WHERE o.translator_id = t.user_id AND o.status = 'pending')
      AND NOT EXISTS (SELECT 1 FROM offers o WHERE o.reservation_id = ? AND o.translator_id = t.user_id)
    ORDER BY t.user_id`).all(r.city_id, r.id);
  return rows.filter((t) => {
    const L = JSON.parse(t.langs);
    const F = JSON.parse(t.fields || '["general"]');
    const fieldOk = r.field === 'general' || F.includes(r.field);
    const carOk = !r.car || carReady(t, r.party);
    return L.includes(r.origin_lang) && L.includes(r.dest_lang) && fieldOk && carOk && genderOk(r, t) && !busyAt(t.user_id, startOf(r), r.id);
  });
}

// اگر پیشنهاد بازی نیست، به نفر بعدی پیشنهاد بده
function offerNext(r) {
  if (!SEARCHABLE.includes(r.status)) return;
  if (db.prepare("SELECT 1 FROM offers WHERE reservation_id = ? AND status = 'pending'").get(r.id)) return;
  const c = eligibleTranslators(r)[0];
  if (!c) return;
  db.prepare('INSERT INTO offers (reservation_id, translator_id, status, expires_at, created_at) VALUES (?, ?, ?, ?, ?)')
    .run(r.id, c.user_id, 'pending', now() + TIMING.OFFER_MS, now());
}

// موتور تطبیق: پیشنهادهای منقضی، سقف جستجو، و مرحله‌های زمان‌دار
const INTERVIEW_MIN = 10;          // مدت مصاحبه‌ی زنده (سند ۵)
// اتاق ویدئویی درون‌برنامه‌ای وجود ندارد؛ هماهنگی مصاحبه با یادداشت مدیر انجام می‌شود
const INTERVIEW_REMINDER_MS = 60 * 60 * 1000; // یادآوری یک ساعت قبل از نوبت
const DOC_NAME_FA = { car_docs: 'مدارک خودرو (بیمه‌نامه)', licence: 'گواهینامه‌ی رانندگی', ipd_permit: 'مجوز ورود IPD',
  criminal_record: 'گواهی عدم سوءپیشینه' };
function notifyExpiry(t) {
  const soon = db.prepare(`SELECT id, user_id, kind, expires_at FROM translator_documents
    WHERE status = 'approved' AND expires_at IS NOT NULL AND expires_at <= ?`).all(t + 30 * DAY_MS);
  const ins = db.prepare('INSERT OR IGNORE INTO translator_notifications (user_id, doc_id, kind, created_at) VALUES (?, ?, ?, ?)');
  for (const d of soon) ins.run(d.user_id, d.id, d.expires_at < t ? 'expired' : 'expiring', t);
}

function notifyInterviews(t) {
  const due = db.prepare(`SELECT id, booked_user_id FROM interview_slots WHERE status = 'booked' AND booked_user_id IS NOT NULL
    AND starts_at - ? <= ? AND starts_at + ? > ?`).all(INTERVIEW_REMINDER_MS, t, INTERVIEW_MIN * 60000, t);
  for (const sl of due) {
    const ref = 'slot:' + sl.id;
    db.prepare(`INSERT INTO translator_notifications (user_id, kind, created_at, ref)
      SELECT ?, 'interview_reminder', ?, ? WHERE NOT EXISTS (SELECT 1 FROM translator_notifications WHERE user_id = ? AND kind = 'interview_reminder' AND ref = ?)`)
      .run(sl.booked_user_id, t, ref, sl.booked_user_id, ref);
  }
}

function sweep() {
  const t = now();
  notifyExpiry(t);
  notifyInterviews(t);
  db.prepare("UPDATE offers SET status = 'expired', decided_at = ? WHERE status = 'pending' AND expires_at <= ?").run(t, t);
  db.prepare("UPDATE change_requests SET status = 'expired', decided_at = ? WHERE status = 'pending' AND expires_at <= ?").run(t, t);
  db.prepare("UPDATE extension_requests SET status = 'expired', decided_at = ? WHERE status = 'pending' AND expires_at <= ?").run(t, t);
  const list = db.prepare("SELECT * FROM reservations WHERE status IN ('searching','waiting_schedule','matching','unmatched_ask')").all();
  for (const r of list) {
    if (r.kind === 'instant' && r.status === 'searching' && t - r.search_started_at >= TIMING.INSTANT_SEARCH_MS) {
      setStatus(r.id, 'no_match'); closeOffers(r.id); continue;
    }
    if (r.kind === 'scheduled') {
      if (r.status === 'waiting_schedule' && t >= r.scheduled_at - TIMING.SCHEDULE_MATCH_BEFORE_MS) {
        setStatus(r.id, 'matching');
      } else if (r.status === 'matching' && t >= r.scheduled_at - TIMING.SCHEDULE_ASK_BEFORE_MS) {
        setStatus(r.id, 'unmatched_ask'); closeOffers(r.id);
      } else if (r.status === 'unmatched_ask' && t >= r.scheduled_at) {
        // بدون پاسخ تا لحظه‌ی قرار: لغو خودکار و رایگان
        setStatus(r.id, 'cancelled'); closeOffers(r.id);
      }
    }
  }
  for (const r of db.prepare("SELECT * FROM reservations WHERE status IN ('searching','matching')").all()) offerNext(r);
}

// نام و خودروی مترجمِ تطبیق‌یافته برای نمایش به مسافر (از پروفایل ثبت‌نامی؛ بدون داده‌ی خصوصی)
function matchedTranslatorInfo(r) {
  if (!r.translator_id) return { translator_name: null, translator_car: null };
  const t = db.prepare('SELECT profile FROM translators WHERE user_id = ?').get(r.translator_id);
  let p = {}; try { p = JSON.parse((t && t.profile) || '{}'); } catch (e) {}
  return {
    translator_name: [p.first_name, p.last_name].filter(Boolean).join(' ') || null,
    translator_car: p.car_model || null,
  };
}

// کد امنیتی شروع خدمت در پایگاه داده رمزنگاری‌شده نگه داشته می‌شود (AES-256-GCM با همان کلید مدارک)؛
// فقط مسافرِ صاحب رزرو آن را از سرور می‌گیرد. ردیف‌های قدیمیِ متن ساده هم خوانده می‌شوند تا رزرو باز خراب نشود.
const SERVICE_CODE_PREFIX = 'enc1:';
function encryptServiceCode(code) {
  return SERVICE_CODE_PREFIX + encryptDoc(Buffer.from(String(code), 'utf8')).toString('base64');
}
function plainServiceCode(r) {
  const raw = r && r.service_code;
  if (!raw) return null;
  if (!String(raw).startsWith(SERVICE_CODE_PREFIX)) return String(raw); // رزرو قدیمی پیش از رمزنگاری
  try { return decryptDoc(Buffer.from(String(raw).slice(SERVICE_CODE_PREFIX.length), 'base64')).toString('utf8'); }
  catch (e) { return null; }
}

// نمای مسافر از یک رزرو (بدون اطلاعات داخلی)
function reservationView(r) {
  return {
    id: r.id, kind: r.kind, status: r.status,
    origin_lang: r.origin_lang, dest_lang: r.dest_lang, field: r.field,
    place: r.place, notes: r.notes, gender_pref: r.gender_pref, hours: r.hours,
    scheduled_at: r.scheduled_at ? new Date(r.scheduled_at).toISOString() : null,
    total: r.total, base: r.base == null ? undefined : r.base, tax: r.tax == null ? undefined : r.tax,
    matched: !!r.translator_id, cancel_after_match: !!r.cancel_after_match,
    ...matchedTranslatorInfo(r),
    pay_method: r.pay_method || null, pay_state: r.pay_state || null,
    service_code: plainServiceCode(r),
    service_started: !!r.service_started_at,
    service_started_at: r.service_started_at ? new Date(r.service_started_at).toISOString() : null,
    finished_at: r.finished_at ? new Date(r.finished_at).toISOString() : null,
    finish_requested: !!r.finish_requested_at,
    finished_by: r.finished_by || null,
    lat: r.lat == null ? null : r.lat, lng: r.lng == null ? null : r.lng,
    created_at: r.created_at,
    pending_change: pendingChangeOf(r.id),
    pending_extension: pendingExtensionOf(r.id),
    last_extension_status: lastExtensionStatusOf(r.id),
  };
}
function pendingChangeOf(rid) {
  const pc = db.prepare("SELECT id, changes, expires_at FROM change_requests WHERE reservation_id = ? AND status = 'pending'").get(rid);
  return pc ? { id: pc.id, changes: JSON.parse(pc.changes), expires_at: new Date(pc.expires_at).toISOString() } : null;
}
function pendingExtensionOf(rid) {
  const pe = db.prepare("SELECT id, extra_hours, extra_base, extra_tax, expires_at FROM extension_requests WHERE reservation_id = ? AND status = 'pending'").get(rid);
  return pe ? { id: pe.id, extra_hours: pe.extra_hours, extra_total: pe.extra_base + pe.extra_tax, expires_at: new Date(pe.expires_at).toISOString() } : null;
}
function lastExtensionStatusOf(rid) {
  const le = db.prepare('SELECT status FROM extension_requests WHERE reservation_id = ? ORDER BY id DESC LIMIT 1').get(rid);
  return le ? le.status : null;
}

function activeTranslator(res, u) {
  const t = db.prepare('SELECT status FROM translators WHERE user_id = ?').get(u.id);
  if (!t || !t.status.startsWith('active_')) { send(res, 403, { error: 'not_active' }); return false; }
  return true;
}
const parseId = (v) => { const n = Number(v); return Number.isInteger(n) && n > 0 ? n : null; };

// ---------- مسافر: رزرو ----------
route('GET', '/api/traveler/bookings', async (req, res) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const rows = db.prepare('SELECT * FROM reservations WHERE traveler_id = ? ORDER BY created_at DESC').all(u.id);
  send(res, 200, { bookings: rows.map(reservationView) });
});

route('POST', '/api/traveler/bookings', async (req, res) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const b = await readJson(req, 64 * 1024);
  const kind = b.kind === 'scheduled' ? 'scheduled' : b.kind === 'instant' ? 'instant' : null;
  if (!kind) return send(res, 400, { error: 'invalid_kind' });
  if (!requireFeature(res, 'traveler_booking')) return;
  if (!requireFeature(res, kind === 'instant' ? 'instant_booking' : 'scheduled_booking')) return;
  if (b.car && !requireFeature(res, 'car_mode')) return;
  const cityRes = resolveCity(b.city_id, 'traveler');
  if (cityRes.error) return send(res, cityRes.status, { error: cityRes.error });
  if (!LANGS.has(b.origin_lang) || !LANGS.has(b.dest_lang)) return send(res, 400, { error: 'invalid_language' });
  const field = b.field || (b.category === 'medical' ? 'medical' : b.category === 'business' ? 'business' : 'general');
  if (!FIELDS.has(field)) return send(res, 400, { error: 'invalid_field' });
  const place = String(b.place || '').trim();
  if (!place || place.length > 200) return send(res, 400, { error: 'invalid_place' });
  // مختصات محل ملاقات (از نقشه‌ی اپ مسافر)؛ اگر فرستاده شده باشد باید معتبر باشد تا مترجم بتواند مسیریابی کند.
  let lat = null, lng = null;
  if (b.lat !== undefined && b.lat !== null && b.lng !== undefined && b.lng !== null) {
    lat = Number(b.lat); lng = Number(b.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      return send(res, 400, { error: 'invalid_coords' });
    }
  }
  const notes = String(b.notes || '').slice(0, 500);
  const gender = GENDER_PREF.has(b.gender_pref) ? b.gender_pref : 'any';
  const travelerGender = b.traveler_gender === 'male' || b.traveler_gender === 'female' ? b.traveler_gender : null;
  const hours = Math.min(Math.max(Number(b.hours) || 1, 1), 12);
  const car = b.car ? 1 : 0;
  const category = Object.keys(getJsonSetting('hourly_tariffs')).includes(b.category) ? b.category : 'general';
  const party = Math.min(Math.max(Number(b.party) || 1, 1), 20);
  let scheduledAt = null;
  if (kind === 'scheduled') {
    scheduledAt = Date.parse(b.scheduled_at);
    if (!Number.isFinite(scheduledAt)) return send(res, 400, { error: 'invalid_time' });
    if (scheduledAt - now() < TIMING.SCHEDULE_MIN_LEAD_MS) return send(res, 400, { error: 'too_soon' });
  }
  const t = now();
  // خدمت قبل از مالیات است؛ مالیات روی خدمت محاسبه و همراه با آن ذخیره می‌شود (سند ۷.۳)
  const tariffs = getJsonSetting('hourly_tariffs');
  const hourlyRate = tariffs[category];
  const base = (hourlyRate + car * getSetting('car_fee_per_hour')) * hours;
  const tax = Math.round(base * PRICING.TAX_PERCENT / 100);
  const status = kind === 'instant' ? 'searching' : 'waiting_schedule';
  // کد امنیتی شروع خدمت را سرور صادر می‌کند (۵ رقم)؛ مسافر هنگام شروع آن را به مترجم اعلام می‌کند.
  const serviceCode = String(crypto.randomInt(10000, 100000));
  const info = db.prepare(`INSERT INTO reservations (traveler_id, kind, origin_lang, dest_lang, field, place, notes, traveler_name, gender_pref,
      scheduled_at, status, search_started_at, total, net, created_at, updated_at, traveler_gender, hours, car, party, base, tax, city_id, service_code, lat, lng)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .run(u.id, kind, b.origin_lang, b.dest_lang, field, place, notes, String(b.traveler_name || '').slice(0, 80), gender,
      scheduledAt, status, t, base + tax, Math.round(base * PRICING.TRANSLATOR_SHARE), t, t,
      travelerGender, hours, car, party, base, tax, cityRes.city.id, encryptServiceCode(serviceCode), lat, lng);
  sweep();
  const row = db.prepare('SELECT * FROM reservations WHERE id = ?').get(info.lastInsertRowid);
  send(res, 201, reservationView(row));
});

function ownReservation(res, u, params) {
  const id = parseId(params.id);
  const r = id && db.prepare('SELECT * FROM reservations WHERE id = ? AND traveler_id = ?').get(id, u.id);
  if (!r) { send(res, 404, { error: 'not_found' }); return null; }
  return r;
}

route('POST', '/api/traveler/bookings/:id/cancel', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (!CANCELLABLE.includes(r.status) && r.status !== 'matched') return send(res, 409, { error: 'not_cancellable' });
  if (r.service_started_at) return send(res, 409, { error: 'service_already_started' });
  const afterMatch = r.status === 'matched';
  db.prepare('UPDATE reservations SET status = ?, cancel_after_match = ?, updated_at = ? WHERE id = ?')
    .run('cancelled', afterMatch ? 1 : 0, now(), r.id);
  closeOffers(r.id);
  send(res, 200, { ok: true, fee_percent: afterMatch ? PRICING.CANCEL_FEE_PERCENT : 0 });
});

route('POST', '/api/traveler/bookings/:id/retry', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (r.status === 'no_match' && r.kind === 'instant') {
    db.prepare("UPDATE reservations SET status = 'searching', search_started_at = ?, updated_at = ? WHERE id = ?").run(now(), now(), r.id);
  } else if (r.status === 'unmatched_ask') {
    setStatus(r.id, 'matching');
  } else return send(res, 409, { error: 'retry_not_allowed' });
  sweep();
  send(res, 200, { ok: true });
});

route('POST', '/api/traveler/bookings/:id/convert', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  if (!requireFeature(res, 'booking_convert')) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (!(r.status === 'no_match' && r.kind === 'instant')) return send(res, 409, { error: 'convert_not_allowed' });
  const b = await readJson(req);
  const at = Date.parse(b.scheduled_at);
  if (!Number.isFinite(at)) return send(res, 400, { error: 'invalid_time' });
  if (at - now() < TIMING.SCHEDULE_MIN_LEAD_MS) return send(res, 400, { error: 'too_soon' });
  db.prepare("UPDATE reservations SET kind = 'scheduled', scheduled_at = ?, status = 'waiting_schedule', updated_at = ? WHERE id = ?").run(at, now(), r.id);
  sweep();
  send(res, 200, { ok: true });
});

// ---------- پایان خدمت و پرداخت (سند ۷.۳ و تصمیم‌های ۴۷ و ۴۸) ----------
// روش‌های پرداخت را مدیر فعال می‌کند؛ پرداخت آنلاین هنوز درگاه واقعی ندارد (شبیه‌سازی).

function settleIfBoth(r) {
  const t = now();
  if (r.traveler_paid && r.translator_confirmed) {
    db.prepare("UPDATE reservations SET pay_state = 'settled', status = 'done', updated_at = ? WHERE id = ?").run(t, r.id);
    return true;
  }
  return false;
}

// مترجم کد امنیتی شروع خدمت را از مسافر می‌گیرد و ثبت می‌کند؛ شروع خدمت فقط با کد درست ممکن است.
// پس از ۵ کد اشتباه، بررسی کد برای این رزرو قفل می‌شود و پرونده باید از پشتیبانی پیگیری شود.
// Private canonical state for service-control reconciliation. Never expose the passenger's code.
route('GET', '/api/translator/missions/:id', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const id = parseId(params.id);
  const r = id && db.prepare('SELECT * FROM reservations WHERE id = ? AND translator_id = ?').get(id, u.id);
  if (!r) return send(res, 404, { error: 'not_found' });
  send(res, 200, { reservation_id: r.id, status: r.status, started: !!r.service_started_at,
    service_started_at: r.service_started_at ? new Date(r.service_started_at).toISOString() : null,
    finish_requested: !!r.finish_requested_at, hours: r.hours, total: r.total, net: r.net,
    pay_method: r.pay_method || null, pay_state: r.pay_state || null,
    confirmed: !!r.translator_confirmed, traveler_paid: !!r.traveler_paid });
});

route('POST', '/api/translator/missions/:id/verify-code', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const id = parseId(params.id);
  const r = id && db.prepare("SELECT * FROM reservations WHERE id = ? AND translator_id = ? AND status = 'matched'").get(id, u.id);
  if (!r) return send(res, 404, { error: 'not_found' });
  const storedCode = plainServiceCode(r);
  if (!storedCode) return send(res, 409, { error: 'no_service_code' });
  if (r.service_started_at) return send(res, 200, { ok: true, already_started: true });
  if ((r.service_code_attempts || 0) >= 5) return send(res, 423, { error: 'code_locked' });
  const b = await readJson(req);
  const code = String(b.code || '').replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/\D/g, '');
  const given = Buffer.from(code);
  const want = Buffer.from(storedCode);
  if (given.length !== want.length || !crypto.timingSafeEqual(given, want)) {
    const attempts = (r.service_code_attempts || 0) + 1;
    db.prepare('UPDATE reservations SET service_code_attempts = ?, updated_at = ? WHERE id = ?').run(attempts, now(), r.id);
    return send(res, 401, { error: 'wrong_code', attempts_left: Math.max(0, 5 - attempts) });
  }
  db.prepare('UPDATE reservations SET service_started_at = ?, service_code_attempts = 0, updated_at = ? WHERE id = ?').run(now(), now(), r.id);
  send(res, 200, { ok: true, started: true });
});

// مترجم به‌تنهایی خدمت را تمام نمی‌کند؛ فقط «درخواست پایان» می‌فرستد و مسافر باید قبول کند.
// (پایان زودهنگام از سمت مترجم هم فقط در حد درخواست است؛ قبول یا رد با مسافر است.)
route('POST', '/api/translator/missions/:id/finish', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const id = parseId(params.id);
  const r = id && db.prepare("SELECT * FROM reservations WHERE id = ? AND translator_id = ? AND status = 'matched'").get(id, u.id);
  if (!r) return send(res, 404, { error: 'not_found' });
  // درخواست پایان پیش از زمان قرار (رزرو زمان‌دار) ممکن نیست
  if (r.scheduled_at && now() < r.scheduled_at) return send(res, 409, { error: 'too_early' });
  // درخواست پایان فقط پس از شروع خدمت با کد امنیتی مسافر
  if (r.service_code && !r.service_started_at) return send(res, 409, { error: 'not_started' });
  if (r.finish_requested_at) return send(res, 202, { ok: true, pending_finish: true, already_requested: true });
  db.prepare('UPDATE reservations SET finish_requested_at = ?, updated_at = ? WHERE id = ?').run(now(), now(), r.id);
  send(res, 202, { ok: true, pending_finish: true });
});

// اعمال پایان خدمت؛ مبلغ کاملِ توافق‌شده (total) دست نمی‌خورد، حتی اگر مسافر زودتر تمام کند.
function applyFinish(r, by) {
  const t = now();
  db.prepare("UPDATE reservations SET status = 'finished', finished_at = ?, finished_by = ?, finish_requested_at = NULL, updated_at = ? WHERE id = ?")
    .run(t, by, t, r.id);
}

// مسافر هر وقت (حتی زودتر از موعد) می‌تواند خودش خدمت را تمام کند؛ تأیید مترجم لازم نیست،
// اما مبلغ کاملِ رزرو باید پرداخت شود و پرداخت از همین‌جا به بعد ممکن می‌شود.
route('POST', '/api/traveler/bookings/:id/finish', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (r.status !== 'matched') return send(res, 409, { error: 'not_in_service' });
  if (r.service_code && !r.service_started_at) return send(res, 409, { error: 'not_started' });
  applyFinish(r, 'traveler');
  send(res, 200, { ok: true, status: 'finished', finished_by: 'traveler', total: r.total });
});

// قبول درخواست پایان مترجم از سوی مسافر
route('POST', '/api/traveler/bookings/:id/finish-approve', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (r.status !== 'matched' || !r.finish_requested_at) return send(res, 409, { error: 'no_finish_request' });
  applyFinish(r, 'translator');
  send(res, 200, { ok: true, status: 'finished', finished_by: 'translator', total: r.total });
});

// رد درخواست پایان مترجم؛ خدمت ادامه پیدا می‌کند
route('POST', '/api/traveler/bookings/:id/finish-reject', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (r.status !== 'matched' || !r.finish_requested_at) return send(res, 409, { error: 'no_finish_request' });
  db.prepare('UPDATE reservations SET finish_requested_at = NULL, updated_at = ? WHERE id = ?').run(now(), r.id);
  send(res, 200, { ok: true, status: 'matched' });
});

route('POST', '/api/traveler/bookings/:id/payment', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (r.status !== 'finished' && r.status !== 'done') return send(res, 409, { error: 'not_payable' });
  if (r.status === 'done') return send(res, 409, { error: 'already_paid' });
  const b = await readJson(req);
  const t = now();
  if (b.method === 'cash') {
    if (!PAYMENTS.CASH) return send(res, 409, { error: 'method_disabled' });
    db.prepare("UPDATE reservations SET pay_method = 'cash', traveler_paid = 1, pay_state = 'awaiting_cash', updated_at = ? WHERE id = ?").run(t, r.id);
    settleIfBoth(db.prepare('SELECT * FROM reservations WHERE id = ?').get(r.id));
  } else if (b.method === 'online') {
    if (!PAYMENTS.ONLINE) return send(res, 409, { error: 'method_disabled' });
    db.prepare("UPDATE reservations SET pay_method = 'online', traveler_paid = 1, pay_state = 'settled', status = 'done', updated_at = ? WHERE id = ?").run(t, r.id);
  } else return send(res, 400, { error: 'invalid_method' });
  const fresh = db.prepare('SELECT status, pay_state FROM reservations WHERE id = ?').get(r.id);
  send(res, 200, { ok: true, status: fresh.status, pay_state: fresh.pay_state });
});

route('POST', '/api/traveler/bookings/:id/dispute', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (r.status !== 'finished' || r.pay_method !== 'cash') return send(res, 409, { error: 'not_disputable' });
  db.prepare("UPDATE reservations SET pay_state = 'disputed', updated_at = ? WHERE id = ?").run(now(), r.id);
  send(res, 200, { ok: true, pay_state: 'disputed' });
});

// مترجم: تأیید دریافت نقدی. با تأیید مسافر، رزرو تسویه و انجام‌شده می‌شود.
route('POST', '/api/translator/missions/:id/cash-confirm', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const id = parseId(params.id);
  const r = id && db.prepare("SELECT * FROM reservations WHERE id = ? AND translator_id = ? AND status = 'finished' AND pay_method = 'cash'").get(id, u.id);
  if (!r) return send(res, 404, { error: 'not_found' });
  if (r.pay_state === 'disputed') return send(res, 409, { error: 'disputed' });
  db.prepare('UPDATE reservations SET translator_confirmed = 1, updated_at = ? WHERE id = ?').run(now(), r.id);
  const settled = settleIfBoth(db.prepare('SELECT * FROM reservations WHERE id = ?').get(r.id));
  send(res, 200, { ok: true, settled, waiting_traveler: !settled });
});

route('POST', '/api/translator/missions/:id/cash-dispute', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const id = parseId(params.id);
  const r = id && db.prepare("SELECT * FROM reservations WHERE id = ? AND translator_id = ? AND status = 'finished' AND pay_method = 'cash'").get(id, u.id);
  if (!r) return send(res, 404, { error: 'not_found' });
  db.prepare("UPDATE reservations SET pay_state = 'disputed', updated_at = ? WHERE id = ?").run(now(), r.id);
  send(res, 200, { ok: true, pay_state: 'disputed' });
});

// مترجم: پرداخت‌های منتظر تأیید (پایان‌یافته و تسویه‌نشده)
route('GET', '/api/translator/payments', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const rows = db.prepare("SELECT id, place, traveler_name, total, net, pay_method, pay_state, translator_confirmed FROM reservations WHERE translator_id = ? AND status = 'finished' AND (pay_state IS NULL OR pay_state != 'settled') ORDER BY finished_at").all(u.id);
  send(res, 200, { payments: rows.map((r) => ({ reservation_id: r.id, place: r.place, travelerName: r.traveler_name, total: r.total, net: r.net,
    pay_method: r.pay_method, pay_state: r.pay_state, confirmed: !!r.translator_confirmed })) });
});

// ---------- ثبت‌نام مترجم روی سرور (مراحل ۱ تا ۵) ----------
// پس از ثبت، پرونده فقط «در انتظار بررسی نهایی» می‌شود؛ هیچ فعال‌سازی خودکاری نیست (سند ۷.۳).
// زبان‌ها و زمینه‌ها همان مقادیری هستند که تطبیق استفاده می‌کند.
const REG_DONE = new Set(['active_general', 'active_specialized']);
const REG_CLOSED = new Set(['rejected', 'suspended', 'deleted']);
const REG_LANGS = ['fa', 'ar', 'en'];
const REG_FIELDS = ['general', 'medical', 'legal', 'business'];
const clip = (v, max) => String(v || '').trim().slice(0, max);
const pick = (arr, allowed) => [...new Set((Array.isArray(arr) ? arr : []).filter((x) => allowed.includes(x)))];

route('POST', '/api/translator/registration', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  const b = await readJson(req);
  if (!requireFeature(res, 'translator_registration')) return;
  const cityRes = resolveCity(b.city_id, 'translator');
  if (cityRes.error) return send(res, cityRes.status, { error: cityRes.error });
  if (b.nda !== true || b.charter !== true) return send(res, 400, { error: 'consent_required' });
  if (b.gender !== 'male' && b.gender !== 'female') return send(res, 400, { error: 'gender_required' });
  const first = clip(b.first_name, 60), last = clip(b.last_name, 60);
  if (!first || !last) return send(res, 400, { error: 'name_required' });
  const langs = pick(b.languages, REG_LANGS);
  if (langs.length < 1) return send(res, 400, { error: 'languages_required' });
  const fields = pick(b.fields, REG_FIELDS);
  if (fields.length < 1) return send(res, 400, { error: 'fields_required' });
  const postal = String(b.postal_code == null ? '' : b.postal_code).replace(/[^0-9]/g, '');
  if (postal && postal.length !== 10) return send(res, 400, { error: 'postal_code_invalid' });
  const profile = JSON.stringify({
    first_name: first, last_name: last, city: cityRes.city.name_fa, postal_code: postal || null,
    car: b.car === true, car_model: clip(b.car_model, 60),
    car_capacity: Math.min(Math.max(Math.trunc(Number(b.car_capacity)) || 0, 0), 8) || null,
    interview_at: clip(b.interview_at, 40),
    charter_at: now(), nda_at: now(),
  });
  const cur = db.prepare('SELECT status FROM translators WHERE user_id = ?').get(u.id);
  if (cur && REG_CLOSED.has(cur.status)) return send(res, 409, { error: 'registration_closed', status: cur.status });
  const next = !cur || cur.status === 'registered' || cur.status === 'in_progress' ? 'pending_review' : cur.status;
  db.prepare(`INSERT INTO translators (user_id, status, gender, profile, langs, fields, updated_at, city_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
              ON CONFLICT(user_id) DO UPDATE SET status = excluded.status, gender = excluded.gender, profile = excluded.profile,
                langs = excluded.langs, fields = excluded.fields, updated_at = excluded.updated_at,
                city_id = CASE WHEN translators.status LIKE 'active_%' THEN translators.city_id ELSE excluded.city_id END`)
    .run(u.id, next, b.gender, profile, JSON.stringify(langs), JSON.stringify(fields), now(), cityRes.city.id);
  send(res, 200, { status: next, languages: langs, fields });
});

// ---------- مدارک مترجم (رمزنگاری‌شده، سند ۴.۲ و ۶.۱) ----------
// فایل‌ها با AES-256-GCM رمز می‌شوند؛ کلید از HZ_DOC_KEY خوانده می‌شود.
// مترجم فقط وضعیت را می‌بیند؛ محتوا فقط برای تیم احراز (ادمین) باز می‌شود.
const DOC_KINDS = new Set(['nid_card', 'selfie', 'portrait', 'address_proof', 'criminal_record', 'drug_free',
  'ipd_permit', 'cip_permit', 'specialty_cert', 'car_docs', 'licence']);
// گواهی تخصصی هر حوزه جداگانه ثبت می‌شود: specialty_cert:<field>
const DOC_MIMES = { 'image/jpeg': 'jpg', 'image/png': 'png', 'application/pdf': 'pdf' };
const DOC_MAX_BYTES = 5 * 1024 * 1024;
const DOC_EXPIRING = new Set(['car_docs', 'licence', 'ipd_permit', 'criminal_record']);
const DAY_MS = 24 * 60 * 60 * 1000;
// پایان روز تاریخ انقضا به وقت تهران (+03:30)
const expiryEnd = (d) => { const t = Date.parse(`${d}T23:59:59+03:30`); return Number.isNaN(t) ? null : t; };
const DOC_KEY = crypto.createHash('sha256').update(process.env.HZ_DOC_KEY || 'hz-dev-only-doc-key').digest();
if (!process.env.HZ_DOC_KEY) {
  if (!DEV) { console.error('خطا: HZ_DOC_KEY برای اجرای غیرتوسعه لازم است.'); process.exit(1); }
  console.log('هشدار: HZ_DOC_KEY تنظیم نشده؛ کلید توسعه استفاده می‌شود.');
}
// امضای فایل: محتوای واقعی باید با نوع اعلام‌شده یکی باشد
const DOC_SIGNATURES = { jpg: [[0xff, 0xd8, 0xff]], png: [[0x89, 0x50, 0x4e, 0x47]], pdf: [[0x25, 0x50, 0x44, 0x46]] };
const sigOk = (buf, ext) => (DOC_SIGNATURES[ext] || []).some((sig) => sig.every((b, i) => buf[i] === b));
const encryptDoc = (buf) => {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', DOC_KEY, iv);
  const enc = Buffer.concat([c.update(buf), c.final()]);
  return Buffer.concat([iv, c.getAuthTag(), enc]);
};
const decryptDoc = (blob) => {
  const d = crypto.createDecipheriv('aes-256-gcm', DOC_KEY, blob.subarray(0, 12));
  d.setAuthTag(blob.subarray(12, 28));
  return Buffer.concat([d.update(blob.subarray(28)), d.final()]);
};

route('POST', '/api/translator/documents', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (Number(req.headers['content-length'] || 0) > DOC_MAX_BYTES * 1.4) return send(res, 413, { error: 'file_too_large' });
  const b = await readJson(req, DOC_MAX_BYTES * 1.4);
  if (!DOC_KINDS.has(b.kind) && !/^specialty_cert:(general|medical|legal|business)$/.test(String(b.kind))) return send(res, 400, { error: 'invalid_kind' });
  const m = /^data:([a-z\/+]+);base64,(.+)$/i.exec(String(b.data || ''));
  if (!m || !DOC_MIMES[m[1].toLowerCase()]) return send(res, 400, { error: 'invalid_file_type' });
  const raw = Buffer.from(m[2], 'base64');
  if (!raw.length) return send(res, 400, { error: 'empty_file' });
  if (raw.length > DOC_MAX_BYTES) return send(res, 413, { error: 'file_too_large' });
  if (!sigOk(raw, DOC_MIMES[m[1].toLowerCase()])) return send(res, 400, { error: 'file_content_mismatch' });
  let expires = null;
  if (DOC_EXPIRING.has(b.kind)) {
    expires = expiryEnd(String(b.expires_at || '').trim());
    if (expires === null) return send(res, 400, { error: 'expiry_required' });
    if (expires < now()) return send(res, 400, { error: 'expiry_in_past' });
  }
  const t = db.prepare('SELECT status FROM translators WHERE user_id = ?').get(u.id);
  if (!t) return send(res, 409, { error: 'registration_required' });
  if (REG_CLOSED.has(t.status)) return send(res, 409, { error: 'registration_closed', status: t.status });
  const ts = now();
  db.prepare("DELETE FROM translator_documents WHERE user_id = ? AND kind = ? AND status IN ('uploaded', 'rejected')").run(u.id, b.kind);
  db.prepare(`INSERT INTO translator_documents (user_id, kind, status, mime, size, blob, expires_at, created_at, updated_at)
              VALUES (?, ?, 'uploaded', ?, ?, ?, ?, ?, ?)`).run(u.id, b.kind, m[1].toLowerCase(), raw.length, encryptDoc(raw), expires, ts, ts);
  send(res, 200, { ok: true, kind: b.kind, status: 'uploaded' });
});

route('GET', '/api/translator/documents', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  const rows = db.prepare(`SELECT id, kind, status, size, reject_reason, expires_at, updated_at FROM translator_documents
    WHERE user_id = ? AND status != 'superseded' ORDER BY kind`).all(u.id);
  const t = now();
  send(res, 200, { documents: rows.map((r) => ({ kind: r.kind, status: r.status, size: r.size,
    reject_reason: r.reject_reason || '', updated_at: new Date(r.updated_at).toISOString(),
    expires_at: r.expires_at ? new Date(r.expires_at).toISOString() : null,
    expired: !!r.expires_at && r.expires_at < t,
    expiring_soon: !!r.expires_at && r.expires_at >= t && r.expires_at - t <= 30 * DAY_MS })) });
});

// ---------- مترجم: پیشنهادها و آنلاین ----------
// Read effective presence without changing matching, score or profile data.
route('GET', '/api/translator/online', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const t = db.prepare('SELECT online FROM translators WHERE user_id = ?').get(u.id);
  const enabled = featureOn('translator_online');
  send(res, 200, { online: enabled && !!(t && t.online), enabled });
});

route('PATCH', '/api/translator/online', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const b = await readJson(req);
  if (!b || typeof b.online !== 'boolean') return send(res, 400, { error: 'invalid_online' });
  if (b.online === true && !requireFeature(res, 'translator_online')) return;
  const g = b.gender === 'male' || b.gender === 'female' ? b.gender : null;
  db.prepare(`UPDATE translators SET online = ?, updated_at = ?,
      gender = COALESCE(?, gender), accept_any = COALESCE(?, accept_any) WHERE user_id = ?`)
    .run(b.online ? 1 : 0, now(), g, typeof b.accept_any === 'boolean' ? (b.accept_any ? 1 : 0) : null, u.id);
  if (b.online) sweep();
  send(res, 200, { online: !!b.online });
});

route('GET', '/api/translator/offers', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  sweep();
  const t = db.prepare('SELECT online FROM translators WHERE user_id = ?').get(u.id);
  const rows = db.prepare(`SELECT o.id AS offer_id, o.expires_at, r.* FROM offers o JOIN reservations r ON r.id = o.reservation_id
    WHERE o.translator_id = ? AND o.status = 'pending' ORDER BY o.created_at`).all(u.id);
  // قبل از پذیرش: فقط ساعت/تاریخ، مبدا-مقصد، نشانی ملاقات، نام مسافر، یادداشت و سهم خالص (بدون جنسیت)
  const changeRows = db.prepare(`SELECT c.id, c.changes, c.expires_at, r.place, r.traveler_name, r.net, r.kind, r.scheduled_at
    FROM change_requests c JOIN reservations r ON r.id = c.reservation_id
    WHERE r.translator_id = ? AND c.status = 'pending' AND c.expires_at > ?`).all(u.id, now());
  const extRows = db.prepare(`SELECT e.id, e.reservation_id, e.extra_hours, e.extra_net, e.expires_at, r.place, r.traveler_name, r.net
    FROM extension_requests e JOIN reservations r ON r.id = e.reservation_id
    WHERE r.translator_id = ? AND e.status = 'pending' AND e.expires_at > ?`).all(u.id, now());
  send(res, 200, { online: !!(t && t.online),
    extensions: extRows.map((e) => ({ id: e.id, reservation_id: e.reservation_id, place: e.place, traveler_name: e.traveler_name,
      extra_hours: e.extra_hours, extra_net: e.extra_net, new_net: (e.net || 0) + e.extra_net, expires_at: new Date(e.expires_at).toISOString() })),
    changes: changeRows.map((c) => ({ id: c.id, place: c.place, traveler_name: c.traveler_name,
    kind: c.kind, scheduled_at: c.scheduled_at ? new Date(c.scheduled_at).toISOString() : null, changes: JSON.parse(c.changes), expires_at: new Date(c.expires_at).toISOString() })),
    offers: rows.map((r) => ({
    id: r.offer_id, kind: r.kind, origin_lang: r.origin_lang, dest_lang: r.dest_lang, field: r.field,
    place: r.place, traveler_name: r.traveler_name, notes: r.notes,
    scheduled_at: r.scheduled_at ? new Date(r.scheduled_at).toISOString() : null,
    net: r.net, expires_at: new Date(r.expires_at).toISOString(),
  })) });
});

route('POST', '/api/translator/offers/:id/accept', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const id = parseId(params.id);
  const o = id && db.prepare('SELECT * FROM offers WHERE id = ? AND translator_id = ?').get(id, u.id);
  if (!o) return send(res, 404, { error: 'not_found' });
  const r = db.prepare('SELECT * FROM reservations WHERE id = ?').get(o.reservation_id);
  if (o.status !== 'pending' || o.expires_at <= now()) return send(res, 410, { error: 'offer_expired' });
  if (!SEARCHABLE.includes(r.status)) return send(res, 409, { error: 'no_longer_available' });
  db.transaction(() => {
    db.prepare("UPDATE reservations SET status = 'matched', translator_id = ?, matched_at = ?, updated_at = ? WHERE id = ?").run(u.id, now(), now(), r.id);
    db.prepare("UPDATE offers SET status = 'accepted', decided_at = ? WHERE id = ?").run(now(), o.id);
    db.prepare("UPDATE offers SET status = 'withdrawn', decided_at = ? WHERE reservation_id = ? AND status = 'pending'").run(now(), r.id);
  })();
  send(res, 200, { ok: true, reservation_id: r.id });
});

route('POST', '/api/translator/offers/:id/decline', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const id = parseId(params.id);
  const o = id && db.prepare("SELECT * FROM offers WHERE id = ? AND translator_id = ? AND status = 'pending'").get(id, u.id);
  if (!o) return send(res, 404, { error: 'not_found' });
  db.prepare("UPDATE offers SET status = 'declined', decided_at = ? WHERE id = ?").run(now(), o.id);
  sweep();
  send(res, 200, { ok: true });
});

// لغو توسط مترجم پس از پذیرش: بدون جریمه‌ی پولی، امتیاز کم می‌شود و ماموریت دوباره تطبیق می‌شود
route('POST', '/api/translator/missions/:id/cancel', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const id = parseId(params.id);
  const r = id && db.prepare("SELECT * FROM reservations WHERE id = ? AND translator_id = ? AND status = 'matched'").get(id, u.id);
  if (!r) return send(res, 404, { error: 'not_found' });
  if (r.service_started_at) return send(res, 409, { error: 'service_already_started' });
  const t = now();
  let next = 'searching';
  if (r.kind === 'scheduled') next = t >= r.scheduled_at - TIMING.SCHEDULE_MATCH_BEFORE_MS ? 'matching' : 'waiting_schedule';
  db.transaction(() => {
    db.prepare(`UPDATE reservations SET status = ?, translator_id = NULL, matched_at = NULL, search_started_at = ?, updated_at = ? WHERE id = ?`)
      .run(next, t, t, r.id);
    db.prepare('UPDATE translators SET score = MAX(0, score - 5), updated_at = ? WHERE user_id = ?').run(t, u.id);
  })();
  sweep();
  send(res, 200, { ok: true, reassigned: next !== 'waiting_schedule' });
});

route('GET', '/api/translator/missions', async (req, res) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const from = now() - 3600 * 1000;
  const fromReservations = db.prepare(`SELECT * FROM reservations WHERE translator_id = ? AND status = 'matched'
      AND COALESCE(scheduled_at, matched_at) > ? ORDER BY COALESCE(scheduled_at, matched_at)`).all(u.id, from)
    .map((r) => ({ id: 'R' + r.id, reservation_id: r.id, code: 'R-' + r.id, purpose: r.field, travelerName: r.traveler_name, place: r.place,
      lat: r.lat == null ? null : r.lat, lng: r.lng == null ? null : r.lng,
      startAt: new Date(r.scheduled_at || r.matched_at).toISOString(), total: r.total, net: r.net, status: 'accepted', started: !!r.service_started_at, finish_requested: !!r.finish_requested_at }));
  // ماموریت‌های آزمایشی تزریقی (فقط حالت توسعه)
  const fromDev = db.prepare(`SELECT id, code, purpose, traveler_name, place, start_at, total, net, status FROM missions
      WHERE translator_id = ? AND status = 'accepted' AND start_at > ?`).all(u.id, from)
    .map((m) => ({ id: m.id, code: m.code, purpose: m.purpose, travelerName: m.traveler_name, place: m.place,
      startAt: new Date(m.start_at).toISOString(), total: m.total, net: m.net, status: m.status }));
  const all = fromReservations.concat(fromDev).sort((a, b) => Date.parse(a.startAt) - Date.parse(b.startAt));
  send(res, 200, { missions: all });
});

// ---------- تغییر رزرو پس از پذیرش ----------
const CHANGE_COLUMNS = { scheduled_at: 'time', place: 'place', origin_lang: 'lang', dest_lang: 'lang', field: 'field',
  hours: 'duration', car: 'car', party: 'party', gender_pref: 'gender' };
const CHANGE_WINDOW_MS = 5 * 60 * 1000 * SCALE;   // مهلت پاسخ مترجم
const CHANGE_LIMIT = 3;                            // حداکثر تغییر مهم
const CHANGE_CUTOFF_MS = 30 * 60 * 1000 * SCALE;   // زیر ۳۰ دقیقه مانده، تغییر مهم پیشنهاد نمی‌شود

// اعتبارسنجی فیلدهای درخواست؛ یادداشت همیشه آزاد است
function parseChanges(b, r) {
  const out = {};
  if ('scheduled_at' in b) {
    if (r.kind !== 'scheduled') return { error: 'time_not_applicable' };
    const at = Date.parse(b.scheduled_at);
    if (!Number.isFinite(at)) return { error: 'invalid_time' };
    if (at - now() < TIMING.SCHEDULE_MIN_LEAD_MS) return { error: 'too_soon' };
    out.scheduled_at = at;
  }
  if ('place' in b) { const v = String(b.place || '').trim(); if (!v || v.length > 200) return { error: 'invalid_place' }; out.place = v; }
  if ('origin_lang' in b) { if (!LANGS.has(b.origin_lang)) return { error: 'invalid_language' }; out.origin_lang = b.origin_lang; }
  if ('dest_lang' in b) { if (!LANGS.has(b.dest_lang)) return { error: 'invalid_language' }; out.dest_lang = b.dest_lang; }
  if ('field' in b) { if (!FIELDS.has(b.field)) return { error: 'invalid_field' }; out.field = b.field; }
  if ('hours' in b) out.hours = Math.min(Math.max(Number(b.hours) || 1, 1), 24);
  if ('car' in b) out.car = b.car ? 1 : 0;
  if ('party' in b) out.party = Math.min(Math.max(Number(b.party) || 1, 1), 20);
  if ('gender_pref' in b) { if (!GENDER_PREF.has(b.gender_pref)) return { error: 'invalid_gender' }; out.gender_pref = b.gender_pref; }
  if ('notes' in b) out.notes = String(b.notes || '').slice(0, 500);
  return { changes: out, important: Object.keys(out).some((k) => k in CHANGE_COLUMNS) };
}

// اعمال تغییرها روی رزرو؛ اگر زمان یا مشخصات عوض شود، تطبیق از نو حساب می‌شود
function applyChanges(r, changes) {
  const keys = Object.keys(changes);
  if (!keys.length) return;
  const sets = keys.map((k) => `${k} = ?`).join(', ');
  db.prepare(`UPDATE reservations SET ${sets}, updated_at = ? WHERE id = ?`).run(...keys.map((k) => changes[k]), now(), r.id);
  const important = keys.some((k) => k in CHANGE_COLUMNS);
  if (!r.translator_id && important) {
    closeOffers(r.id);
    if ('scheduled_at' in changes) {
      setStatus(r.id, now() >= changes.scheduled_at - TIMING.SCHEDULE_MATCH_BEFORE_MS ? 'matching' : 'waiting_schedule');
    } else if (r.status === 'no_match') {
      setStatus(r.id, 'searching');
    }
  }
  sweep();
}

route('POST', '/api/traveler/bookings/:id/change', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  if (!requireFeature(res, 'booking_change')) return;
  const r = ownReservation(res, u, params); if (!r) return;
  if (r.status === 'cancelled') return send(res, 409, { error: 'not_changeable' });
  const b = await readJson(req);
  const parsed = parseChanges(b, r);
  if (parsed.error) return send(res, 400, { error: parsed.error });
  if (!Object.keys(parsed.changes).length) return send(res, 400, { error: 'nothing_to_change' });
  if (!parsed.important) { applyChanges(r, parsed.changes); return send(res, 200, { applied: true }); }
  if (r.scheduled_at && now() >= r.scheduled_at - CHANGE_CUTOFF_MS) return send(res, 409, { error: 'too_late_for_change' });
  if (!r.translator_id) { applyChanges(r, parsed.changes); return send(res, 200, { applied: true }); }
  // مترجم پذیرفته: رضایت او لازم است
  if (db.prepare("SELECT 1 FROM change_requests WHERE reservation_id = ? AND status = 'pending'").get(r.id)) return send(res, 409, { error: 'change_pending' });
  const count = db.prepare('SELECT COUNT(*) AS n FROM change_requests WHERE reservation_id = ?').get(r.id).n;
  if (count >= CHANGE_LIMIT) return send(res, 409, { error: 'change_limit' });
  const info = db.prepare('INSERT INTO change_requests (reservation_id, changes, status, expires_at, created_at) VALUES (?, ?, ?, ?, ?)')
    .run(r.id, JSON.stringify(parsed.changes), 'pending', now() + CHANGE_WINDOW_MS, now());
  send(res, 202, { pending: true, id: info.lastInsertRowid, expires_at: new Date(now() + CHANGE_WINDOW_MS).toISOString() });
});

// ---------- تمدید زمان خدمت در جریان (سند: تمدید فقط با تأیید مترجم) ----------
// قیمت تمدید از روی همان نرخ لحظه‌ی ثبت رزرو حساب می‌شود (base/hours) تا تغییر تعرفه‌ی مدیر روی رزرو باز اثر نگذارد.
function extensionQuote(r, extraHours) {
  const perHourBase = r.hours > 0 ? Math.round(r.base / r.hours) : 0;
  const extraBase = perHourBase * extraHours;
  const extraTax = r.base > 0 ? Math.round(extraBase * r.tax / r.base) : 0;
  const extraNet = r.base > 0 ? Math.round(extraBase * r.net / r.base) : 0;
  return { extraBase, extraTax, extraNet };
}
const EXTENSION_MAX_HOURS = 12; // سقف کل مدت خدمت، هماهنگ با سقف ثبت رزرو

route('POST', '/api/traveler/bookings/:id/extend', async (req, res, url, params) => {
  const u = requireUser(req, res, 'traveler'); if (!u) return;
  const r = ownReservation(res, u, params); if (!r) return;
  const b = await readJson(req);
  const extra = Math.trunc(Number(b.extra_hours)) || 1;
  if (extra < 1 || extra > 4) return send(res, 400, { error: 'invalid_extension' });
  // تمدید فقط وقتی خدمت واقعاً شروع شده و هنوز تمام نشده است
  if (r.status !== 'matched' || !r.service_started_at || !r.translator_id) return send(res, 409, { error: 'extension_not_allowed' });
  if ((r.hours || 1) + extra > EXTENSION_MAX_HOURS) return send(res, 409, { error: 'extension_limit' });
  if (db.prepare("SELECT 1 FROM extension_requests WHERE reservation_id = ? AND status = 'pending'").get(r.id)) {
    return send(res, 409, { error: 'extension_pending' });
  }
  const q = extensionQuote(r, extra);
  const info = db.prepare(`INSERT INTO extension_requests (reservation_id, extra_hours, extra_base, extra_tax, extra_net, status, expires_at, created_at)
    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)`)
    .run(r.id, extra, q.extraBase, q.extraTax, q.extraNet, now() + CHANGE_WINDOW_MS, now());
  send(res, 202, { pending: true, id: info.lastInsertRowid, extra_hours: extra,
    extra_total: q.extraBase + q.extraTax, new_total: r.total + q.extraBase + q.extraTax,
    expires_at: new Date(now() + CHANGE_WINDOW_MS).toISOString() });
});

function ownExtension(res, u, params) {
  const id = parseId(params.id);
  const e = id && db.prepare('SELECT e.*, r.translator_id AS tid FROM extension_requests e JOIN reservations r ON r.id = e.reservation_id WHERE e.id = ?').get(id);
  if (!e || e.tid !== u.id) { send(res, 404, { error: 'not_found' }); return null; }
  return e;
}
route('GET', '/api/translator/extensions/:id', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const e = ownExtension(res, u, params); if (!e) return;
  send(res, 200, { id: e.id, reservation_id: e.reservation_id,
    status: e.status === 'pending' && e.expires_at <= now() ? 'expired' : e.status,
    extra_hours: e.extra_hours, extra_total: e.extra_base + e.extra_tax, extra_net: e.extra_net,
    expires_at: new Date(e.expires_at).toISOString() });
});
route('POST', '/api/translator/extensions/:id/accept', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const e = ownExtension(res, u, params); if (!e) return;
  if (e.status !== 'pending' || e.expires_at <= now()) return send(res, 410, { error: 'extension_expired' });
  const r = db.prepare('SELECT * FROM reservations WHERE id = ?').get(e.reservation_id);
  if (!r || r.status !== 'matched') return send(res, 409, { error: 'extension_not_allowed' });
  db.prepare("UPDATE extension_requests SET status = 'accepted', decided_at = ? WHERE id = ?").run(now(), e.id);
  db.prepare(`UPDATE reservations SET hours = hours + ?, base = base + ?, tax = tax + ?, total = total + ?, net = net + ?, updated_at = ? WHERE id = ?`)
    .run(e.extra_hours, e.extra_base, e.extra_tax, e.extra_base + e.extra_tax, e.extra_net, now(), r.id);
  send(res, 200, { ok: true });
});
route('POST', '/api/translator/extensions/:id/reject', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const e = ownExtension(res, u, params); if (!e) return;
  if (e.status !== 'pending' || e.expires_at <= now()) return send(res, 410, { error: 'extension_expired' });
  db.prepare("UPDATE extension_requests SET status = 'rejected', decided_at = ? WHERE id = ?").run(now(), e.id);
  send(res, 200, { ok: true });
});

function ownChange(res, u, params) {
  const id = parseId(params.id);
  const c = id && db.prepare('SELECT c.*, r.translator_id AS tid FROM change_requests c JOIN reservations r ON r.id = c.reservation_id WHERE c.id = ?').get(id);
  if (!c || c.tid !== u.id) { send(res, 404, { error: 'not_found' }); return null; }
  return c;
}
route('POST', '/api/translator/changes/:id/accept', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const c = ownChange(res, u, params); if (!c) return;
  if (c.status !== 'pending' || c.expires_at <= now()) return send(res, 410, { error: 'change_expired' });
  const r = db.prepare('SELECT * FROM reservations WHERE id = ?').get(c.reservation_id);
  db.prepare("UPDATE change_requests SET status = 'accepted', decided_at = ? WHERE id = ?").run(now(), c.id);
  applyChanges(r, JSON.parse(c.changes));
  send(res, 200, { ok: true });
});
route('POST', '/api/translator/changes/:id/reject', async (req, res, url, params) => {
  const u = requireUser(req, res, 'translator'); if (!u) return;
  if (!activeTranslator(res, u)) return;
  const c = ownChange(res, u, params); if (!c) return;
  if (c.status !== 'pending') return send(res, 410, { error: 'change_expired' });
  db.prepare("UPDATE change_requests SET status = 'rejected', decided_at = ? WHERE id = ?").run(now(), c.id);
  send(res, 200, { ok: true });
});


// ---------- قابلیت‌ها، شهرها و ممیزی (پنل مدیر) ----------
function featuresNow() {
  let stored = {};
  try { stored = JSON.parse(settingRaw('features') || '{}'); } catch (e) { stored = {}; }
  return resolveFeatures(stored);
}
function featureOn(key) { return featuresNow()[key] === true; }
function requireFeature(res, key) {
  if (featureOn(key)) return true;
  send(res, 409, { error: 'feature_disabled', feature: key });
  return false;
}
function audit(action, detail) {
  db.prepare('INSERT INTO audit_log (created_at, action, detail) VALUES (?, ?, ?)').run(now(), action, JSON.stringify(detail || {}));
}
function defaultCityId() {
  const v = Number(getSetting('default_city_id'));
  return Number.isInteger(v) && v > 0 ? v : null;
}
// شهر درخواست: city_id صریح یا شهر پیش‌فرض؛ باید وجود داشته و برای آن نقش فعال باشد
function resolveCity(raw, role) {
  const id = raw === undefined || raw === null || raw === '' ? defaultCityId() : parseId(raw);
  if (!id) return { error: 'city_required', status: 400 };
  const c = db.prepare('SELECT id, name_fa, traveler_enabled, translator_enabled FROM cities WHERE id = ?').get(id);
  if (!c) return { error: 'invalid_city', status: 400 };
  const on = role === 'traveler' ? c.traveler_enabled : c.translator_enabled;
  if (!on) return { error: 'city_not_active', status: 409 };
  return { city: c };
}

route('GET', '/api/admin/features', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const on = featuresNow();
  send(res, 200, { features: FEATURE_KEYS.map((k) => ({ key: k, group: FEATURES[k].group, label: FEATURES[k].label,
    implemented: FEATURES[k].implemented, requires: FEATURES[k].requires, effect: FEATURES[k].effect, enabled: on[k] })) });
});

route('PUT', '/api/admin/features', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const b = await readJson(req);
  const before = featuresNow();
  const v = validateFeaturePatch(b, before);
  if (!v.ok) return send(res, v.status, { error: v.error, key: v.key, requires: v.requires });
  const changed = FEATURE_KEYS.filter((k) => v.next[k] !== before[k]);
  const stored = {};
  for (const k of FEATURE_KEYS) stored[k] = v.next[k];
  db.transaction(() => {
    db.prepare('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value')
      .run('features', JSON.stringify(stored));
    // خاموش‌کردن ثبت‌نام آنلاین: مترجمان آنلاین به حالت آفلاین برگردند
    if (changed.includes('translator_online') && !v.next.translator_online) {
      db.prepare('UPDATE translators SET online = 0').run();
    }
  })();
  audit('features.update', { changed: changed.map((k) => ({ key: k, enabled: v.next[k] })) });
  send(res, 200, { ok: true, changed });
});

// ورودی شهر: اعتبارسنجی سخت‌گیرانه؛ partial یعنی فقط فیلدهای ارسالی بررسی شوند
function cityInput(b, partial) {
  const out = {};
  if (!partial || b.name_fa !== undefined) {
    const nf = typeof b.name_fa === 'string' ? b.name_fa.trim() : '';
    if (nf.length < 2 || nf.length > 40) return { error: 'invalid_name' };
    out.name_fa = nf;
  }
  if (b.name_en !== undefined) {
    const ne = typeof b.name_en === 'string' ? b.name_en.trim() : '';
    if (ne.length > 40 || !/^[A-Za-z][A-Za-z .'-]*$/.test(ne) && ne !== '') return { error: 'invalid_name_en' };
    out.name_en = ne;
  }
  if (b.province !== undefined) {
    if (typeof b.province !== 'string' || b.province.length > 60) return { error: 'invalid_province' };
    out.province = b.province.trim();
  }
  if (!partial || b.lat !== undefined) {
    const la = typeof b.lat === 'number' ? b.lat : NaN;
    if (!Number.isFinite(la) || la < -90 || la > 90) return { error: 'invalid_lat' };
    out.lat = la;
  }
  if (!partial || b.lng !== undefined) {
    const lo = typeof b.lng === 'number' ? b.lng : NaN;
    if (!Number.isFinite(lo) || lo < -180 || lo > 180) return { error: 'invalid_lng' };
    out.lng = lo;
  }
  if (!partial || b.radius_km !== undefined) {
    const r = b.radius_km === undefined ? 30 : b.radius_km;
    if (!Number.isInteger(r) || r < 1 || r > 200) return { error: 'invalid_radius' };
    out.radius_km = r;
  }
  for (const k of ['traveler_enabled', 'translator_enabled']) {
    if (!partial || b[k] !== undefined) {
      const val = b[k] === undefined ? true : b[k];
      if (typeof val !== 'boolean') return { error: 'invalid_value', key: k };
      out[k] = val ? 1 : 0;
    }
  }
  return { value: out };
}

const cityView = (c) => ({ id: c.id, name_fa: c.name_fa, name_en: c.name_en, province: c.province, lat: c.lat, lng: c.lng,
  radius_km: c.radius_km, traveler_enabled: c.traveler_enabled === 1, translator_enabled: c.translator_enabled === 1,
  translators: c.translators || 0, open_bookings: c.open_bookings || 0, matched_bookings: c.matched_bookings || 0 });

route('GET', '/api/admin/cities', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const rows = db.prepare(`SELECT c.*,
      (SELECT COUNT(*) FROM translators t WHERE t.city_id = c.id AND t.status LIKE 'active_%') AS translators,
      (SELECT COUNT(*) FROM reservations r WHERE r.city_id = c.id AND r.status IN (${UNMATCHED_SQL})) AS open_bookings,
      (SELECT COUNT(*) FROM reservations r WHERE r.city_id = c.id AND r.status = 'matched') AS matched_bookings
    FROM cities c ORDER BY c.id`).all();
  send(res, 200, { cities: rows.map(cityView), default_city_id: defaultCityId() });
});

route('POST', '/api/admin/cities', async (req, res) => {
  if (!requireAdmin(req, res)) return;
  const b = await readJson(req);
  const v = cityInput(b && typeof b === 'object' ? b : {}, false);
  if (v.error) return send(res, 400, { error: v.error, key: v.key });
  const t = now();
  let id;
  try {
    const r = db.prepare(`INSERT INTO cities (name_fa, name_en, province, lat, lng, radius_km, traveler_enabled, translator_enabled, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(v.value.name_fa, v.value.name_en || '', v.value.province || '', v.value.lat,
      v.value.lng, v.value.radius_km, v.value.traveler_enabled, v.value.translator_enabled, t, t);
    id = Number(r.lastInsertRowid);
  } catch (e) {
    if (/UNIQUE/.test(e.message)) return send(res, 409, { error: 'city_exists' });
    throw e;
  }
  audit('city.create', { id, name_fa: v.value.name_fa });
  send(res, 201, { ok: true, id });
});

route('PATCH', '/api/admin/cities/:id', async (req, res, url, params) => {
  if (!requireAdmin(req, res)) return;
  const id = parseId(params.id);
  const cur = id && db.prepare('SELECT * FROM cities WHERE id = ?').get(id);
  if (!cur) return send(res, 404, { error: 'not_found' });
  const b = await readJson(req);
  if (!b || typeof b !== 'object' || Array.isArray(b)) return send(res, 400, { error: 'invalid_body' });
  const v = cityInput(b, true);
  if (v.error) return send(res, 400, { error: v.error, key: v.key });
  const keys = Object.keys(v.value);
  if (!keys.length) return send(res, 400, { error: 'nothing_to_change' });
  const next = { ...cur, ...v.value };
  const closing = cur.traveler_enabled === 1 && next.traveler_enabled === 0;
  const openIds = closing
    ? db.prepare(`SELECT id FROM reservations WHERE city_id = ? AND status IN (${UNMATCHED_SQL})`).all(id).map((x) => x.id)
    : [];
  if (openIds.length && b.confirm_cancel !== true) {
    return send(res, 409, { error: 'open_bookings', count: openIds.length });
  }
  db.transaction(() => {
    db.prepare(`UPDATE cities SET name_fa = ?, name_en = ?, province = ?, lat = ?, lng = ?, radius_km = ?,
      traveler_enabled = ?, translator_enabled = ?, updated_at = ? WHERE id = ?`)
      .run(next.name_fa, next.name_en, next.province, next.lat, next.lng, next.radius_km,
        next.traveler_enabled, next.translator_enabled, now(), id);
    // رزروهای باز این شهر (هنوز مترجم ندارند) لغو می‌شوند؛ بدون کارمزد، چون تطبیق نشده است
    for (const rid of openIds) { closeOffers(rid); setStatus(rid, 'cancelled'); }
  })();
  audit('city.update', { id, changed: keys, cancelled: openIds.length });
  send(res, 200, { ok: true, cancelled: openIds.length });
});

route('GET', '/api/admin/audit', async (req, res, url) => {
  if (!requireAdmin(req, res)) return;
  const lim = Math.min(Math.max(Number(url.searchParams.get('limit')) || 100, 1), 500);
  const rows = db.prepare('SELECT id, created_at, action, detail FROM audit_log ORDER BY id DESC LIMIT ?').all(lim);
  send(res, 200, { entries: rows.map((r) => ({ id: r.id, at: new Date(r.created_at).toISOString(), action: r.action, detail: JSON.parse(r.detail) })) });
});

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const pathname = url.pathname;
  for (const [k, v] of Object.entries(securityHeaders(pathname, FRAME_ANCESTORS))) res.setHeader(k, v);
  if (!pathname.startsWith('/api/')) {
    if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405); return res.end(); }
    return serveStatic(req, res, pathname);
  }
  let r = null; const params = {};
  for (const x of routes) {
    if (x.method !== req.method) continue;
    const m = pathname.match(x.re);
    if (m) { r = x; x.keys.forEach((k, i) => { params[k] = decodeURIComponent(m[i + 1]); }); break; }
  }
  if (!r) return send(res, 404, { error: 'not_found' });
  try {
    await r.handler(req, res, url, params);
  } catch (e) {
    const status = e.status || 500;
    if (status === 500) console.error('[server]', e);
    if (!res.headersSent) send(res, status, { error: status === 500 ? 'server_error' : e.message });
  }
});

if (require.main === module) {
  // بررسی ایمنی پیکربندی انتشار بالاتر (ابتدای فایل) انجام شده است.
  setInterval(sweep, Math.max(100, 3000 * SCALE)).unref(); // موتور تطبیق هر ۳ ثانیه (در حالت فشرده کوتاه‌تر)
  server.listen(PORT, '0.0.0.0', () => {
    console.log(`همراه: http://0.0.0.0:${PORT}  (حالت توسعه: ${DEV ? 'روشن' : 'خاموش'}، پایگاه داده: ${DB_PATH})`);
    if (!DEV && !SMS.configured) console.log('هشدار: پیامک‌دهنده تنظیم نشده است (HZ_SMS_PROVIDER/HZ_SMS_API_KEY)؛ ارسال کد ورود پاسخ 503 می‌دهد.');
  });
}

module.exports = { server, db, CONFIG, normalizePhone };
