/* Guidance only: never sends location, dispatches help or starts a call automatically. */
(function () {
  'use strict';
  var panel = document.getElementById('inline-sos-panel');
  var button = document.getElementById('sos-btn');
  var closeButton = document.getElementById('translator-support-close');
  var status = document.getElementById('translator-support-status');
  var call = document.getElementById('translator-support-call');
  var phone = document.getElementById('translator-support-phone');
  var retry = document.getElementById('translator-support-retry');
  var controller = null, timer = null, version = 0;

  function normalizedPhone(raw) {
    if (typeof raw !== 'string') return null;
    var value = raw.trim().replace(/[۰-۹]/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'.indexOf(d); })
      .replace(/[٠-٩]/g, function (d) { return '٠١٢٣٤٥٦٧٨٩'.indexOf(d); });
    // Reject URLs, control characters, USSD, extensions and markup before constructing tel:.
    if (!/^\+?[0-9 ()-]+$/.test(value)) return null;
    value = value.replace(/[ ()-]/g, '');
    return /^\+?[0-9]{7,15}$/.test(value) ? value : null;
  }
  function hideCall() {
    call.classList.add('hidden');
    call.removeAttribute('href');
    phone.textContent = '';
  }
  function stop() {
    version++;
    clearTimeout(timer);
    if (controller) controller.abort();
    controller = null;
    retry.disabled = false;
    hideCall();
  }
  function current(read) { return read === version && !panel.classList.contains('hidden'); }
  async function refresh() {
    stop();
    var read = version, abort = new AbortController();
    controller = abort;
    status.textContent = 'در حال دریافت شمارهٔ پشتیبانی…';
    retry.disabled = true;
    try {
      // Bound both the response and its body, even if a transport ignores AbortSignal.
      var timeout = new Promise(function (_, reject) {
        timer = setTimeout(function () { abort.abort(); reject(new Error('timeout')); }, 10000);
      });
      var config = await Promise.race([(async function () {
        var response = await fetch('/api/config', { cache: 'no-store', signal: abort.signal });
        if (response.status !== 200) throw new Error('config_unavailable');
        return response.json();
      })(), timeout]);
      if (!current(read)) return;
      if (!config || typeof config.support_phone !== 'string') throw new Error('config_invalid');
      if (!config.support_phone.trim()) {
        status.textContent = 'شمارهٔ پشتیبانی هنوز در پنل مدیریت تنظیم نشده است.';
        return;
      }
      var number = normalizedPhone(config.support_phone);
      if (!number) {
        status.textContent = 'شمارهٔ پشتیبانی ثبت‌شده معتبر نیست؛ امکان تماس از این بخش وجود ندارد.';
        return;
      }
      phone.textContent = number;
      call.setAttribute('href', 'tel:' + number);
      call.classList.remove('hidden');
      status.textContent = 'شمارهٔ پشتیبانی از تنظیمات مدیر دریافت شد.';
    } catch (_) {
      if (!current(read)) return;
      hideCall();
      status.textContent = 'شمارهٔ پشتیبانی دریافت نشد. دوباره تلاش کنید.';
    } finally {
      if (read === version) {
        clearTimeout(timer);
        controller = null;
        retry.disabled = false;
      }
    }
  }
  function close() {
    stop();
    panel.classList.add('hidden');
    button.setAttribute('aria-expanded', 'false');
    document.getElementById('sos-chevron').style.transform = 'rotate(0deg)';
  }
  function toggle() {
    if (!panel.classList.contains('hidden')) { close(); button.focus(); return; }
    panel.classList.remove('hidden');
    button.setAttribute('aria-expanded', 'true');
    document.getElementById('sos-chevron').style.transform = 'rotate(180deg)';
    closeButton.focus();
    refresh();
  }
  retry.addEventListener('click', function () { if (!panel.classList.contains('hidden') && !retry.disabled) refresh(); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !panel.classList.contains('hidden')) {
      event.preventDefault(); close(); button.focus();
    }
  });
  document.addEventListener('click', function (event) {
    var nav = event.target.closest && event.target.closest('[data-target]');
    if (nav && nav.dataset.target !== 'workspace') close();
  });
  window.addEventListener('pagehide', close);
  window.HZ_TRANSLATOR_SUPPORT = { toggle: toggle };
})();
