/* Server-confirmed translator service controls. No local success fallback. */
(function () {
  'use strict';
  var busy = new Set();
  var ERROR = 'نتیجهٔ عملیات تأیید نشد. وضعیت مأموریت را بررسی کنید و سپس دوباره تلاش کنید.';
  function id(n) { return Number.isSafeInteger(n) && n > 0; }
  function money(n) { return typeof n === 'number' && Number.isFinite(n) && n >= 0; }
  function timestamp(s) { return typeof s === 'string' && Number.isFinite(Date.parse(s)); }
  function mission(m, rid) {
    if (!m || m.reservation_id !== rid || !id(rid) || !['matched', 'finished', 'done'].includes(m.status) ||
        typeof m.started !== 'boolean' || typeof m.finish_requested !== 'boolean' ||
        !money(m.total) || !money(m.net) || typeof m.hours !== 'number' || !Number.isFinite(m.hours) || m.hours < 1 || m.hours > 24 ||
        (m.started ? !timestamp(m.service_started_at) : m.service_started_at !== null) ||
        (m.finish_requested && !m.started)) throw new Error(ERROR);
    return m;
  }
  function extension(e, eid, rid) {
    if (!e || e.id !== eid || e.reservation_id !== rid || !id(eid) || !id(rid) ||
        !['pending', 'accepted', 'rejected', 'expired'].includes(e.status) ||
        !Number.isInteger(e.extra_hours) || e.extra_hours < 1 || e.extra_hours > 4 ||
        !money(e.extra_total) || !money(e.extra_net) || !timestamp(e.expires_at)) throw new Error(ERROR);
    return e;
  }
  var detailKeys = ['scheduled_at', 'place', 'origin_lang', 'dest_lang', 'field', 'hours', 'car', 'party', 'gender_pref', 'notes'];
  function validDetail(k, v) {
    if (k === 'scheduled_at') return v === null || (typeof v === 'number' && Number.isFinite(v) && v > 0);
    if (k === 'place' || k === 'notes') return typeof v === 'string' && (k === 'notes' || v.trim().length > 0) && v.length <= (k === 'notes' ? 500 : 200);
    if (k === 'origin_lang' || k === 'dest_lang') return ['fa', 'ar', 'en', 'tr', 'fr', 'ru', 'zh'].includes(v);
    if (k === 'field') return ['general', 'medical', 'legal', 'business'].includes(v);
    if (k === 'hours' || k === 'party') return typeof v === 'number' && Number.isFinite(v) && v >= 1 && v <= (k === 'hours' ? 24 : 20);
    if (k === 'car') return v === 0 || v === 1;
    if (k === 'gender_pref') return ['any', 'female', 'male'].includes(v);
    return false;
  }
  function validChanges(changes) {
    return changes && typeof changes === 'object' && !Array.isArray(changes) && Object.keys(changes).length > 0 &&
      Object.keys(changes).every(function (k) { return detailKeys.includes(k) && validDetail(k, changes[k]) && (k !== 'scheduled_at' || changes[k] !== null); });
  }
  function sameChanges(a, b) {
    return validChanges(a) && validChanges(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(function (k) { return Object.prototype.hasOwnProperty.call(b, k) && a[k] === b[k]; });
  }
  function change(c, cid, rid) {
    if (!c || !id(cid) || c.id !== cid || c.reservation_id !== rid || !id(rid) ||
        !['pending', 'accepted', 'rejected', 'expired'].includes(c.status) || !timestamp(c.expires_at) || !validChanges(c.changes)) throw new Error(ERROR);
    return c;
  }
  function details(m) {
    if (!m.details || !detailKeys.every(function (k) { return Object.prototype.hasOwnProperty.call(m.details, k) && validDetail(k, m.details[k]); }) || m.details.hours !== m.hours) throw new Error(ERROR);
    return m.details;
  }
  function offer(o, oid, rid) {
    if (!o || !id(oid) || o.id !== oid || o.reservation_id !== rid || !id(rid) ||
        !['pending', 'accepted', 'declined', 'expired', 'withdrawn'].includes(o.status) ||
        !timestamp(o.expires_at) || !money(o.net) || typeof o.assigned !== 'boolean') throw new Error(ERROR);
    return o;
  }
  function cash(m) {
    if (!['finished', 'done'].includes(m.status) || m.pay_method !== 'cash' ||
        !['awaiting_cash', 'disputed', 'settled'].includes(m.pay_state) ||
        typeof m.confirmed !== 'boolean' || typeof m.traveler_paid !== 'boolean' ||
        ((m.status === 'done') !== (m.pay_state === 'settled')) ||
        (m.pay_state === 'settled' && (!m.confirmed || !m.traveler_paid))) throw new Error(ERROR);
    return m;
  }
  function key(token, rid) { return token + ':' + rid; }
  function update() {
    var token = window.HZ.load().token;
    document.querySelectorAll('[data-service-mission]').forEach(function (button) {
      button.disabled = busy.has(key(token, Number(button.dataset.serviceMission)));
      button.setAttribute('aria-busy', button.disabled ? 'true' : 'false');
    });
  }
  function bind(button, rid) {
    button.dataset.serviceMission = rid;
    button.disabled = busy.has(key(window.HZ.load().token, rid));
    button.setAttribute('aria-busy', button.disabled ? 'true' : 'false');
  }
  async function run(options) {
    var token = window.HZ.load().token, rid = options.reservation_id;
    if (!token || options.token !== token || !id(rid) || busy.has(key(token, rid))) return;
    var lock = key(token, rid), controller = new AbortController(), timer;
    busy.add(lock); update();
    function current() {
      if (window.HZ.load().token !== token || controller.signal.aborted) throw new Error(ERROR);
    }
    async function request(method, path, body) {
      current();
      var response = await fetch('/api/translator/' + path, {
        method: method, signal: controller.signal, cache: 'no-store',
        headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body)
      });
      var data = await response.json(); current();
      if (!response.ok) {
        if (response.status === 423 && data.error === 'code_locked') throw new Error('کد این رزرو قفل شده است؛ با پشتیبانی هماهنگ کنید.');
        if (response.status === 401 && data.error === 'wrong_code') throw new Error('کد نادرست است.');
        throw new Error(ERROR);
      }
      return { status: response.status, data: data };
    }
    async function readMission() {
      var res = await request('GET', 'missions/' + rid);
      if (res.status !== 200) throw new Error(ERROR);
      return mission(res.data, rid);
    }
    async function readExtension() {
      var res = await request('GET', 'extensions/' + options.id);
      if (res.status !== 200) throw new Error(ERROR);
      return extension(res.data, options.id, rid);
    }
    async function work() {
      var before, e, res, after, decided;
      if (options.action === 'offer-accept' || options.action === 'offer-decline') {
        async function readOffer() {
          var view = await request('GET', 'offers/' + options.id);
          if (view.status !== 200) throw new Error(ERROR);
          return offer(view.data, options.id, rid);
        }
        before = await readOffer();
        if (before.status !== 'pending' || before.assigned || before.net !== options.net || Date.parse(before.expires_at) <= Date.now()) throw new Error(ERROR);
        var accepting = options.action === 'offer-accept';
        res = await request('POST', 'offers/' + options.id + (accepting ? '/accept' : '/decline'));
        if (res.status !== 200 || !res.data || res.data.ok !== true || (accepting && res.data.reservation_id !== rid)) throw new Error(ERROR);
        after = await readOffer();
        if (after.status !== (accepting ? 'accepted' : 'declined') || after.net !== before.net || after.expires_at !== before.expires_at || after.assigned !== accepting) throw new Error(ERROR);
        if (accepting) {
          var acceptedMission = await readMission();
          if (acceptedMission.status !== 'matched' || acceptedMission.net !== before.net) throw new Error(ERROR);
        }
        return accepting ? 'ماموریت پذیرفته شد.' : 'رد پیشنهاد ثبت شد.';
      }
      before = await readMission();
      if (options.action === 'change-accept' || options.action === 'change-reject') {
        if (before.status !== 'matched') throw new Error(ERROR);
        var priorDetails = details(before);
        async function readChange() {
          var view = await request('GET', 'changes/' + options.id);
          if (view.status !== 200) throw new Error(ERROR);
          return change(view.data, options.id, rid);
        }
        e = await readChange();
        if (e.status !== 'pending' || Date.parse(e.expires_at) <= Date.now() || !sameChanges(e.changes, options.changes)) throw new Error(ERROR);
        var acceptingChange = options.action === 'change-accept';
        res = await request('POST', 'changes/' + options.id + (acceptingChange ? '/accept' : '/reject'));
        if (res.status !== 200 || !res.data || res.data.ok !== true) throw new Error(ERROR);
        decided = await readChange(); after = await readMission();
        var currentDetails = details(after);
        if (decided.status !== (acceptingChange ? 'accepted' : 'rejected') || !sameChanges(decided.changes, e.changes) || decided.expires_at !== e.expires_at ||
            after.status !== 'matched' || after.total !== before.total || after.net !== before.net || after.started !== before.started || after.service_started_at !== before.service_started_at ||
            !detailKeys.every(function (k) { return currentDetails[k] === (acceptingChange && Object.prototype.hasOwnProperty.call(e.changes, k) ? e.changes[k] : priorDetails[k]); })) throw new Error(ERROR);
        return acceptingChange ? 'تغییر پذیرفته شد.' : 'رد تغییر ثبت شد.';
      }
      if (options.action === 'cash-confirm' || options.action === 'cash-dispute') {
        cash(before);
        if (before.status !== 'finished' || before.pay_state !== 'awaiting_cash' || before.confirmed ||
            before.total !== options.total || before.net !== options.net) throw new Error(ERROR);
        res = await request('POST', 'missions/' + rid + '/' + options.action);
        if (res.status !== 200 || !res.data || res.data.ok !== true) throw new Error(ERROR);
        if (options.action === 'cash-confirm') {
          if (typeof res.data.settled !== 'boolean' || typeof res.data.waiting_traveler !== 'boolean' ||
              res.data.settled === res.data.waiting_traveler) throw new Error(ERROR);
        } else if (res.data.pay_state !== 'disputed') throw new Error(ERROR);
        after = cash(await readMission());
        if (after.total !== before.total || after.net !== before.net || after.hours !== before.hours ||
            after.service_started_at !== before.service_started_at) throw new Error(ERROR);
        if (options.action === 'cash-dispute') {
          if (after.status !== 'finished' || after.pay_state !== 'disputed' || after.confirmed !== before.confirmed ||
              after.traveler_paid !== before.traveler_paid) throw new Error(ERROR);
          return 'اختلاف پرداخت ثبت شد.';
        }
        if (!after.confirmed || (res.data.settled
          ? after.status !== 'done' || after.pay_state !== 'settled' || !after.traveler_paid
          : after.status !== 'finished' || after.pay_state !== 'awaiting_cash' || after.traveler_paid)) throw new Error(ERROR);
        return res.data.settled ? 'پرداخت تسویه شد.' : 'دریافت شما ثبت شد؛ منتظر تأیید مسافر.';
      }
      if (before.status !== 'matched') throw new Error(ERROR);
      if (options.action === 'start') {
        var code = String(options.code || '').trim().replace(/[۰-۹]/g, function (c) { return '۰۱۲۳۴۵۶۷۸۹'.indexOf(c); }).replace(/[٠-٩]/g, function (c) { return '٠١٢٣٤٥٦٧٨٩'.indexOf(c); });
        if (!/^\d{5}$/.test(code)) throw new Error('کد امنیتی پنج‌رقمی مسافر را وارد کنید.');
        res = await request('POST', 'missions/' + rid + '/verify-code', { code: code });
        if (res.status !== 200 || res.data.ok !== true || !(res.data.started === true || res.data.already_started === true)) throw new Error(ERROR);
        after = await readMission();
        if (after.status !== 'matched' || !after.started || after.hours !== before.hours || after.total !== before.total || (before.started && before.service_started_at !== after.service_started_at)) throw new Error(ERROR);
        return 'خدمت شروع شد.';
      }
      if (!before.started) throw new Error(ERROR);
      if (options.action === 'finish') {
        res = await request('POST', 'missions/' + rid + '/finish');
        if (res.status !== 202 || res.data.ok !== true || res.data.pending_finish !== true) throw new Error(ERROR);
        after = await readMission();
        if (after.status !== 'matched' || !after.started || !after.finish_requested || after.total !== before.total || after.hours !== before.hours || after.service_started_at !== before.service_started_at) throw new Error(ERROR);
        return 'درخواست پایان برای مسافر فرستاده شد؛ تا تأیید او خدمت ادامه دارد.';
      }
      if (!['accept', 'reject'].includes(options.action)) throw new Error(ERROR);
      e = await readExtension();
      if (e.status !== 'pending' || Date.parse(e.expires_at) <= Date.now()) throw new Error(ERROR);
      res = await request('POST', 'extensions/' + options.id + '/' + options.action);
      if (res.status !== 200 || res.data.ok !== true) throw new Error(ERROR);
      decided = await readExtension(); after = await readMission();
      var accept = options.action === 'accept';
      if (decided.status !== (accept ? 'accepted' : 'rejected') || decided.extra_hours !== e.extra_hours || decided.extra_total !== e.extra_total || decided.extra_net !== e.extra_net ||
          after.status !== 'matched' || !after.started || after.service_started_at !== before.service_started_at ||
          after.hours !== before.hours + (accept ? e.extra_hours : 0) || after.total !== before.total + (accept ? e.extra_total : 0) || after.net !== before.net + (accept ? e.extra_net : 0)) throw new Error(ERROR);
      return accept ? 'تمدید پذیرفته شد؛ زمان و مبلغ خدمت به‌روز شد.' : 'تمدید رد شد.';
    }
    try {
      // Bound the whole read/mutate/read operation, including a response body
      // that stalls. Abort alone is insufficient with some transports.
      var timeout = new Promise(function (_, reject) {
        timer = setTimeout(function () { controller.abort(); reject(new Error(ERROR)); }, 10000);
      });
      var message = await Promise.race([work(), timeout]); current();
      window.HZ.toast(message);
    } catch (err) {
      if (window.HZ.load().token === token) window.HZ.toast(err.message === 'کد نادرست است.' || err.message === 'کد امنیتی پنج‌رقمی مسافر را وارد کنید.' || err.message === 'کد این رزرو قفل شده است؛ با پشتیبانی هماهنگ کنید.' ? err.message : ERROR);
    } finally {
      clearTimeout(timer); controller.abort(); busy.delete(lock); update();
      if (window.HZ.load().token === token && options.refresh) options.refresh();
    }
  }
  window.HZ_MISSION_ACTION = { run: run, bind: bind, update: update, validChanges: validChanges };
})();
