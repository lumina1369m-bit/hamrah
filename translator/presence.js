/* Presence is server state, never a cached shift flag or optimistic switch. */
(function () {
  'use strict';
  var busy = false, owner = null, enabled = null;
  var ERROR = 'وضعیت آمادگی تأیید نشد؛ برای بررسی دوباره تلاش کنید.';
  function token() { return window.HZ.load().token || null; }
  function controls() {
    document.querySelectorAll('[data-presence-control]').forEach(function (b) {
      b.disabled = busy || enabled === false;
      b.setAttribute('aria-busy', busy ? 'true' : 'false');
    });
    var retry = document.getElementById('presence-retry');
    if (retry) { retry.disabled = busy; retry.hidden = window.isShiftActive !== null && enabled !== false; }
  }
  function unknown() {
    window.renderShiftState(false);
    window.isShiftActive = null; owner = null; enabled = null;
    document.getElementById('shift-status-title').textContent = 'وضعیت آمادگی مشخص نیست';
    document.getElementById('shift-status-desc').textContent = ERROR;
    document.getElementById('header-shift-text').textContent = 'وضعیت نامشخص';
    document.getElementById('shift-toggle-btn').setAttribute('aria-pressed', 'mixed');
    var notice = document.getElementById('shift-paused-notice');
    if (notice) notice.classList.add('hidden');
    var state = HZ.load(); state.shift = null; HZ.save(state); controls();
  }
  function apply(data, actor) {
    if (token() !== actor) return;
    owner = actor; enabled = data.enabled;
    window.renderShiftState(data.online);
    document.getElementById('shift-toggle-btn').setAttribute('aria-pressed', String(data.online));
    if (!data.enabled) document.getElementById('shift-status-desc').textContent = 'دریافت مأموریت توسط مدیر غیرفعال است.';
    var state = HZ.load(); state.shift = data.online; HZ.save(state); controls();
  }
  async function run(target, notify) {
    if (busy) return;
    var actor = token();
    if (!actor) { unknown(); return; }
    // A card rendered for a previous account may only refresh, never mutate.
    var change = typeof target === 'boolean' && owner === actor && window.isShiftActive !== null;
    busy = true; controls();
    var controller = new AbortController(), timer;
    function current() { if (token() !== actor || controller.signal.aborted) throw new Error(ERROR); }
    async function request(method, body) {
      current();
      var response = await fetch('/api/translator/online', { method: method, cache: 'no-store', signal: controller.signal,
        headers: { Authorization: 'Bearer ' + actor, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body) });
      var data = await response.json(); current();
      if (response.status !== 200 || !data || typeof data.online !== 'boolean') throw new Error(ERROR);
      if (method === 'GET' && (typeof data.enabled !== 'boolean' || (!data.enabled && data.online))) throw new Error(ERROR);
      return data;
    }
    async function work() {
      var before = await request('GET');
      if (!change) return before;
      if (target && !before.enabled) throw new Error(ERROR);
      var receipt = await request('PATCH', { online: target });
      if (receipt.online !== target) throw new Error(ERROR);
      var after = await request('GET');
      if (after.online !== target) throw new Error(ERROR);
      return after;
    }
    try {
      var timeout = new Promise(function (_, reject) {
        timer = setTimeout(function () { controller.abort(); reject(new Error(ERROR)); }, 10000);
      });
      var result = await Promise.race([work(), timeout]); current(); apply(result, actor);
      if (change) HZ.toast(result.online ? 'آمادگی شما برای دریافت مأموریت ثبت شد.' : 'وضعیت آفلاین شما ثبت شد.');
    } catch (_) {
      if (token() === actor) { unknown(); if (notify) HZ.toast(ERROR); }
    } finally {
      clearTimeout(timer); controller.abort(); busy = false; controls();
    }
  }
  window.HZ_PRESENCE = { set: function (on) { return run(on, true); }, refresh: function () { return run(undefined, true); } };
  var retry = document.createElement('button'); retry.id = 'presence-retry'; retry.type = 'button';
  retry.className = 'text-[12px] font-bold text-primary'; retry.textContent = 'بررسی دوبارهٔ آمادگی';
  retry.setAttribute('aria-label', retry.textContent);
  retry.onclick = function () { return run(undefined, true); };
  var retrySlot = document.getElementById('presence-retry-slot');
  (retrySlot || document.getElementById('shift-status-desc').parentNode).appendChild(retry);
  unknown();
  window.addEventListener('DOMContentLoaded', function () { run(undefined, false); });
  window.addEventListener('focus', function () { run(undefined, false); });
  setInterval(function () { run(undefined, false); }, 15000);
})();
