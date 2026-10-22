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
        !money(m.total) || !money(m.net) || !Number.isInteger(m.hours) || m.hours < 1 || m.hours > 12 ||
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
      var before = await readMission(), e, res, after, decided;
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
  window.HZ_MISSION_ACTION = { run: run, bind: bind, update: update };
})();
