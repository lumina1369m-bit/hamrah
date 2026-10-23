/* Read-only, account-bound notifications. No sample financial or credential claims. */
(function () {
  'use strict';
  var panel = document.getElementById('inline-notifications-panel');
  var button = document.getElementById('notifications-btn');
  var list = document.getElementById('notifications-list');
  var status = document.getElementById('notifications-status');
  var retry = document.getElementById('notifications-retry');
  var controller = null, timer = null, version = 0, owner = null;
  var ERROR = 'دریافت اعلان‌ها انجام نشد. دوباره تلاش کنید.';
  var CHANGED = 'حساب تغییر کرده است؛ اعلان‌ها را دوباره دریافت کنید.';
  function token() { return window.HZ.load().token || null; }
  function stop() {
    version++; clearTimeout(timer);
    if (controller) controller.abort();
    controller = null; retry.disabled = false; list.replaceChildren();
  }
  function valid(rows) {
    return Array.isArray(rows) && rows.length <= 20 && rows.every(function (n) {
      return n && Number.isSafeInteger(n.id) && n.id > 0 &&
        ['doc_rejected', 'expired', 'expiring', 'interview_reminder'].includes(n.kind) &&
        (n.doc_kind === null || typeof n.doc_kind === 'string') && typeof n.doc_name === 'string' &&
        typeof n.created_at === 'string' && Number.isFinite(Date.parse(n.created_at)) &&
        typeof n.text === 'string' && n.text.trim().length > 0 && n.text.length <= 10000;
    }) && new Set(rows.map(function (n) { return n.id; })).size === rows.length;
  }
  function render(rows) {
    list.replaceChildren();
    rows.forEach(function (n) {
      var card = document.createElement('article');
      card.className = 'p-3 rounded-2xl bg-surface-container-low text-[13px] space-y-2';
      card.dataset.notificationId = n.id;
      var text = document.createElement('p'); text.textContent = n.text;
      var time = document.createElement('time'); time.dateTime = n.created_at;
      time.className = 'block text-[11px] text-on-surface-variant';
      time.textContent = HZ.jDate(new Date(n.created_at)) + ' ' + HZ.clock(new Date(n.created_at));
      card.appendChild(text); card.appendChild(time); list.appendChild(card);
    });
  }
  function accountGuard() {
    if (!panel.classList.contains('hidden') && owner !== token()) {
      stop(); owner = token(); status.textContent = CHANGED;
    }
  }
  async function refresh() {
    stop();
    var read = version, actor = token(); owner = actor;
    if (!actor) { status.textContent = 'برای دریافت اعلان‌ها دوباره وارد شوید.'; return; }
    status.textContent = 'در حال دریافت اعلان‌ها…'; retry.disabled = true;
    var abort = new AbortController(); controller = abort;
    try {
      var timeout = new Promise(function (_, reject) {
        timer = setTimeout(function () { abort.abort(); reject(new Error('timeout')); }, 10000);
      });
      var data = await Promise.race([(async function () {
        var response = await fetch('/api/translator/notifications', {
          headers: { Authorization: 'Bearer ' + actor }, cache: 'no-store', signal: abort.signal
        });
        if (response.status !== 200) throw new Error('unavailable');
        return response.json();
      })(), timeout]);
      if (read !== version || panel.classList.contains('hidden')) return;
      if (token() !== actor) { accountGuard(); return; }
      if (!data || !valid(data.notifications)) throw new Error('invalid');
      render(data.notifications);
      status.textContent = data.notifications.length ? 'اعلان‌های ثبت‌شدهٔ این حساب از سرور دریافت شدند.' : 'اعلانی برای این حساب ثبت نشده است.';
    } catch (_) {
      if (read !== version || panel.classList.contains('hidden')) return;
      if (token() !== actor) { accountGuard(); return; }
      list.replaceChildren(); status.textContent = ERROR;
    } finally {
      if (read === version) { clearTimeout(timer); controller = null; retry.disabled = false; }
    }
  }
  function close() {
    stop(); owner = null; panel.classList.add('hidden');
    button.setAttribute('aria-expanded', 'false');
  }
  function toggle() {
    if (!panel.classList.contains('hidden')) { close(); button.focus(); return; }
    panel.classList.remove('hidden'); button.setAttribute('aria-expanded', 'true');
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    document.getElementById('notifications-close').focus(); refresh();
  }
  retry.addEventListener('click', function () { if (!retry.disabled && !panel.classList.contains('hidden')) refresh(); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !panel.classList.contains('hidden')) {
      event.preventDefault(); close(); button.focus();
    }
  });
  window.addEventListener('storage', accountGuard);
  window.addEventListener('pagehide', close);
  setInterval(accountGuard, 1000);
  window.HZ_NOTIFICATIONS = { toggle: toggle, close: close };
})();
