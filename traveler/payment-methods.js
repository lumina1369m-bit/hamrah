/* Payment availability is server-owned. Unknown or failed configuration is closed. */
(function () {
  'use strict';
  var config = null, loading = false, inFlight = null;
  var methods = ['online', 'cash'];
  function el(id) { return document.getElementById(id); }
  function allowed(method) { return !!config && config[method] === true; }
  function selectionAria() {
    methods.forEach(function (method) {
      var button = el('pay-method-' + method);
      if (button) {
        button.setAttribute('aria-pressed', window.payChoice === method ? 'true' : 'false');
        // Selection handlers replace className; never let that reveal a disabled method.
        button.classList.toggle('hidden', !allowed(method));
      }
    });
  }
  function render() {
    var checkout = el('btn-settle-return');
    if (!checkout) return;
    var busy = checkout.getAttribute('aria-busy') === 'true';
    methods.forEach(function (method) {
      var button = el('pay-method-' + method);
      if (button) button.disabled = loading || busy || !allowed(method);
    });
    if (!loading && !busy) {
      if (!allowed(window.payChoice)) window.payChoice = allowed('online') ? 'online' : allowed('cash') ? 'cash' : null;
      // Existing selection handlers update styling and the cash explanation.
      if (window.payChoice) el('pay-method-' + window.payChoice).click();
    }
    // Selection handlers replace className, so apply visibility afterwards.
    methods.forEach(function (method) {
      var button = el('pay-method-' + method);
      if (button) button.classList.toggle('hidden', !allowed(method));
    });
    var available = allowed('cash') || allowed('online');
    var note = el('cash-note');
    if (note && (!available || !config)) note.classList.add('hidden');
    checkout.disabled = loading || !available || checkout.getAttribute('aria-busy') === 'true';
    var status = el('payment-method-status');
    if (status) {
      status.textContent = loading ? 'در حال دریافت روش‌های پرداخت…'
        : !config ? 'روش‌های پرداخت دریافت نشد. دوباره تلاش کنید.'
        : !available ? 'در حال حاضر هیچ روش پرداختی فعال نیست.' : '';
      status.classList.toggle('hidden', !status.textContent);
    }
    var retry = el('btn-refresh-payment-methods');
    if (retry) retry.disabled = loading;
    selectionAria();
  }
  function refresh() {
    if (inFlight) return inFlight;
    loading = true;
    render();
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 10000);
    inFlight = fetch('/api/config', { cache: 'no-store', signal: controller.signal })
      .then(function (response) {
        if (!response.ok) throw new Error('payment_config_unavailable');
        return response.json();
      }).then(function (body) {
        var pm = body.payments;
        // Existing servers return 0/1 for unset defaults and booleans for saved settings.
        var flags = [true, false, 0, 1];
        if (!pm || flags.indexOf(pm.CASH) === -1 || flags.indexOf(pm.ONLINE) === -1) throw new Error('payment_config_unavailable');
        config = { cash: pm.CASH === true || pm.CASH === 1, online: pm.ONLINE === true || pm.ONLINE === 1 };
        return config;
      }).catch(function () {
        config = null;
        throw new Error('payment_config_unavailable');
      }).finally(function () {
        clearTimeout(timer);
        loading = false;
        inFlight = null;
        render();
      });
    return inFlight;
  }
  window.HZ_PAYMENTS = { refresh: refresh, render: render, allowed: allowed };
  document.addEventListener('DOMContentLoaded', function () {
    methods.forEach(function (method) { el('pay-method-' + method).addEventListener('click', selectionAria); });
    el('btn-refresh-payment-methods').addEventListener('click', function () { refresh().catch(function () {}); });
    render();
    refresh().catch(function () {});
  });
})();
