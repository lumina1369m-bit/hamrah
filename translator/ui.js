/* مترجم همراه تشریفات — کتابخانه‌ی مشترک: تنظیمات، ذخیره‌سازی، تاریخ شمسی، اعلان */
(function (w) {
  'use strict';

  // تنظیمات که در نسخه‌ی تولید از پنل مدیریت خوانده می‌شوند
  const CONFIG = {
    OTP_LENGTH: 6,
    OTP_RESEND_SECONDS: 120,
    OTP_MAX_FAILS: 5,
    OTP_LOCK_MINUTES: 10,
    SESSION_DAYS: 30,
    INVITE_SECONDS: 60,           // مهلت پذیرش دعوت (با مسافر یکی است)
    CHANGE_RESPONSE_SECONDS: 300, // مهلت پاسخ به تغییر مهم مسافر
    CHANGE_MIN_LEAD_MINUTES: 30,  // کمتر از این فاصله، تغییر مهم پیشنهاد نمی‌شود
    EXPIRY_REMINDER_DAYS: 30,
    SETTLEMENT_PERIOD: 'روزانه',   // پیش‌فرض پنل مدیریت
    SEARCH_RADIUS_NOTE: '',
    SOS_ESCALATION_MINUTES: 10
  };

  const KEY = 'hz.translator.v1';

  // ---------- ذخیره‌سازی ----------
  const defaultState = () => ({
    session: null,               // { phone, until }
    lock: null,                  // timestamp پایان قفل
    status: 'registered',        // registered | in_progress | pending_review | active_general | active_specialized | rejected | suspended | deleted
    step: 1,
    completed: { 1: false, 2: false, 3: false, 4: false, 5: false },
    profile: { nameFa: '', nameEn: '', nationalId: '', birth: '', gender: '', city: '', acceptFrom: 'all', photo: false, biometric: false, address: false, criminal: false, drug: false, idCard: false, emergency: null },
    languages: [],
    interview: null,             // { slot, result: null|'pass'|'repeat', attempts: [] }
    fields: { tourism: true, pilgrim: true, medical: false, business: false, legal: false, airport: false },
    certs: {},                   // { medical: 'pending'|'approved'|'rejected', ... ipd/cip }
    vehicle: { on: false, model: '', year: '', color: '', capacity: 4, plate: '', docs: {}, licenceOk: false, expiry: { insurance: '', inspection: '' } },
    finance: { sheba: '', holder: '', taxId: '', charter: false, nda: false },
    shift: false,
    missions: [],
    settled: [],
    rating: { score: 4.8, count: 0 },
    cancelCount: 0,
    rejectCount: 0,
    appeal: null,
    log: []
  });

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return defaultState();
      return Object.assign(defaultState(), JSON.parse(raw));
    } catch (e) { return defaultState(); }
  }
  function save(state) { localStorage.setItem(KEY, JSON.stringify(state)); }

  // Same-origin preview proxies can strip Authorization; keep the server-supported fallback too.
  function authHeaders(token, extra) {
    const headers = Object.assign({}, extra || {});
    if (typeof token === 'string' && token.length) {
      headers.Authorization = 'Bearer ' + token;
      headers['X-Auth-Token'] = token;
    }
    return headers;
  }

  // ---------- تاریخ و عدد ----------
  const FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
  const toFa = (v) => String(v).replace(/[0-9]/g, (d) => FA_DIGITS[d]);
  const toEn = (v) => String(v).replace(/[۰-۹]/g, (d) => FA_DIGITS.indexOf(d)).replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
  const money = (n) => toFa(Math.round(n).toLocaleString('en-US')) + ' تومان';
  const pad2 = (n) => String(n).padStart(2, '0');

  const jFmt = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
  const jShort = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { year: 'numeric', month: 'long', day: 'numeric' });
  const hhmm = new Intl.DateTimeFormat('fa-IR', { hour: '2-digit', minute: '2-digit', hour12: false });
  const jFull = (d) => jFmt.format(d);
  const jDate = (d) => jShort.format(d);
  const clock = (d) => hhmm.format(d);

  // تبدیل شمسی به میلادی: با جست‌وجو در اطراف تخمین، همان تقویم Intl نمایش را مبنا می‌گیرد
  const jalParts = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { year: 'numeric', month: 'numeric', day: 'numeric' });
  function jalToGreg(jy, jm, jd) {
    const want = [jy, jm, jd].join('/');
    const guess = new Date(jy + 621, 2 + (jm - 1), 21 + (jd - 1), 12);
    for (let off = -40; off <= 40; off++) {
      const d = new Date(guess.getTime() + off * 86400000);
      const parts = jalParts.formatToParts(d);
      const g = (t) => toEn(parts.find((p) => p.type === t).value);
      if ([g('year'), g('month'), g('day')].join('/') === want) return new Date(d.getFullYear(), d.getMonth(), d.getDate());
    }
    return null;
  }

  function ageFrom(date) {
    const now = new Date();
    let a = now.getFullYear() - date.getFullYear();
    const m = now.getMonth() - date.getMonth();
    if (m < 0 || (m === 0 && now.getDate() < date.getDate())) a--;
    return a;
  }

  // کد ملی ده‌رقمی با رقم کنترل
  function validNationalId(code) {
    if (!/^\d{10}$/.test(code)) return false;
    if (/^(\d)\1{9}$/.test(code)) return false;
    const c = Number(code[9]);
    let s = 0;
    for (let i = 0; i < 9; i++) s += Number(code[i]) * (10 - i);
    const r = s % 11;
    return r < 2 ? c === r : c === 11 - r;
  }

  function validSheba(v) {
    return /^IR\d{24}$/.test(String(v).replace(/\s/g, '').toUpperCase());
  }

  // ---------- اعلان و پیام ----------
  function toast(msg, opts) {
    const el = document.getElementById('hz-toast');
    if (!el) return;
    el.textContent = msg;
    el.setAttribute('role', opts && opts.error ? 'alert' : 'status');
    el.classList.remove('hidden');
    el.classList.add('flex');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.classList.add('hidden'); el.classList.remove('flex'); }, 3600);
  }

  // ---------- شمارنده ----------
  function countdown(seconds, onTick, onDone) {
    let left = seconds;
    onTick(left);
    const t = setInterval(() => {
      left -= 1;
      onTick(left);
      if (left <= 0) { clearInterval(t); onDone && onDone(); }
    }, 1000);
    return () => clearInterval(t);
  }

  // ---------- نشست ----------
  function requireSession(state) {
    if (!state.session || state.session.until < Date.now()) {
      state.session = null;
      save(state);
      return false;
    }
    return true;
  }

  // ---------- وضعیت حساب ----------
  const STATUS_LABEL = {
    registered: 'ثبت‌نام‌شده',
    in_progress: 'در حال احراز',
    pending_review: 'در انتظار بررسی نهایی',
    active_general: 'فعال (عمومی)',
    active_specialized: 'فعال (تخصصی)',
    rejected: 'رد شده',
    suspended: 'تعلیق',
    deleted: 'حذف‌شده'
  };

  /* ماموریت‌های پذیرفته‌شده و آینده (سند مترجم).
     فقط مبلغ کل و سهم خالص مترجم نمایش داده می‌شود؛ مسافر فقط با نام. */
  function acceptedMissions(state) {
    var now = Date.now();
    return (state.missions || [])
      .filter(function (m) { return m.status === 'accepted' && Date.parse(m.startAt) > now - 3600000; })
      .sort(function (a, b) { return Date.parse(a.startAt) - Date.parse(b.startAt); });
  }

  w.HZ = { acceptedMissions, authHeaders, CONFIG, KEY, load, save, defaultState, toFa, toEn, money, jFull, jDate, clock, pad2, jalToGreg, ageFrom, validNationalId, validSheba, toast, countdown, requireSession, STATUS_LABEL };
})(window);
