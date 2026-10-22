'use strict';
// کاتالوگ قابلیت‌های پلتفرم. هر قابلیت در کد تعریف می‌شود؛ روشن/خاموش بودنش در پنل مدیر تعیین می‌شود.
// implemented: false یعنی قابلیت هنوز پیاده‌سازی نشده و نمی‌توان آن را روشن کرد.
// requires: قابلیت‌هایی که باید روشن باشند تا این قابلیت روشن بماند.

const FEATURES = {
  traveler_booking: { group: 'مسافر', label: 'ثبت رزرو توسط مسافر', implemented: true, default: true, requires: [],
    effect: 'خاموش: هیچ رزرو جدیدی ثبت نمی‌شود.' },
  instant_booking: { group: 'مسافر', label: 'رزرو فوری', implemented: true, default: true, requires: ['traveler_booking'],
    effect: 'خاموش: فقط رزرو زمان‌دار ممکن است.' },
  scheduled_booking: { group: 'مسافر', label: 'رزرو زمان‌دار', implemented: true, default: true, requires: ['traveler_booking'],
    effect: 'خاموش: فقط رزرو فوری ممکن است.' },
  booking_change: { group: 'مسافر', label: 'تغییر رزرو پس از تطبیق', implemented: true, default: true, requires: ['traveler_booking'],
    effect: 'خاموش: تغییر مهم پس از پذیرش مترجم ممکن نیست.' },
  booking_convert: { group: 'مسافر', label: 'تبدیل رزرو فوری بدون مترجم به زمان‌دار', implemented: true, default: true,
    requires: ['instant_booking', 'scheduled_booking'], effect: 'خاموش: دکمه‌ی تبدیل نمایش داده نمی‌شود.' },
  car_mode: { group: 'مسافر', label: 'همراهی با خودرو', implemented: true, default: true, requires: ['traveler_booking'],
    effect: 'خاموش: مسافر فقط مأموریت پیاده می‌تواند ثبت کند.' },
  translator_registration: { group: 'مترجم', label: 'ثبت‌نام مترجم', implemented: true, default: true, requires: [],
    effect: 'خاموش: ثبت‌نام مترجم جدید پذیرفته نمی‌شود.' },
  translator_online: { group: 'مترجم', label: 'آنلاین شدن و دریافت پیشنهاد', implemented: true, default: true,
    requires: ['translator_registration'], effect: 'خاموش: هیچ مترجمی پیشنهاد دریافت نمی‌کند.' },
  interview_scheduling: { group: 'مترجم', label: 'رزرو نوبت مصاحبه‌ی زبان', implemented: true, default: true,
    requires: ['translator_registration'], effect: 'خاموش: مترجم نمی‌تواند نوبت مصاحبه بگیرد.' },
  expiry_notifications: { group: 'مترجم', label: 'یادآوری انقضای مدارک', implemented: true, default: true,
    requires: ['translator_registration'], effect: 'خاموش: یادآوری انقضا در اپ مترجم نمایش داده نمی‌شود.' },
  email_login: { group: 'ورود', label: 'ورود با ایمیل', implemented: false, default: false, requires: [],
    effect: 'هنوز پیاده‌سازی نشده است.' },
};

const FEATURE_KEYS = Object.keys(FEATURES);

// وضعیت نهایی همه‌ی قابلیت‌ها: ترکیب مقادیر ذخیره‌شده و پیش‌فرض.
function resolveFeatures(stored) {
  const out = {};
  for (const k of FEATURE_KEYS) {
    const v = stored && Object.prototype.hasOwnProperty.call(stored, k) ? stored[k] : FEATURES[k].default;
    out[k] = FEATURES[k].implemented ? v === true : false;
  }
  return out;
}

// اعتبارسنجی یک تغییر (patch) روی وضعیت فعلی.
// خروجی: { ok: true, next } یا { ok: false, status, error, key }
function validateFeaturePatch(patch, current) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return { ok: false, status: 400, error: 'invalid_body' };
  const keys = Object.keys(patch);
  if (!keys.length) return { ok: false, status: 400, error: 'nothing_to_change' };
  const next = { ...current };
  for (const k of keys) {
    if (!FEATURES[k]) return { ok: false, status: 400, error: 'unknown_feature', key: k };
    if (typeof patch[k] !== 'boolean') return { ok: false, status: 400, error: 'invalid_value', key: k };
    if (patch[k] === true && !FEATURES[k].implemented) return { ok: false, status: 409, error: 'not_implemented', key: k };
    next[k] = patch[k];
  }
  // هیچ قابلیت روشنی نباید به قابلیت خاموش وابسته باشد
  for (const k of FEATURE_KEYS) {
    if (!next[k]) continue;
    for (const dep of FEATURES[k].requires) {
      if (!next[dep]) return { ok: false, status: 409, error: 'dependency_off', key: k, requires: dep };
    }
  }
  return { ok: true, next };
}

module.exports = { FEATURES, FEATURE_KEYS, resolveFeatures, validateFeaturePatch };
