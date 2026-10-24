/* This dialog never sends an emergency alert or starts a call automatically. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var dialog = document.getElementById('support-dialog');
    var status = document.getElementById('support-status');
    var call = document.getElementById('support-call');
    var phone = document.getElementById('support-phone');
    var retry = document.getElementById('support-retry');
    var close = document.getElementById('support-close');
    var controller = null, timer = null, version = 0;

    function normalizedPhone(raw) {
      if (typeof raw !== 'string') return null;
      var value = raw.trim().replace(/[۰-۹]/g, function (digit) { return '۰۱۲۳۴۵۶۷۸۹'.indexOf(digit); })
        .replace(/[٠-٩]/g, function (digit) { return '٠١٢٣٤٥٦٧٨٩'.indexOf(digit); });
      // Reject URLs, control characters, USSD and extension syntax before constructing tel:.
      if (!/^\+?[0-9 ()-]+$/.test(value)) return null;
      value = value.replace(/[ ()-]/g, '');
      return /^\+?[0-9]{7,15}$/.test(value) ? value : null;
    }
    function stop() {
      version++;
      if (controller) controller.abort();
      controller = null;
      clearTimeout(timer);
      retry.disabled = false;
    }
    function hideCall() {
      call.classList.add('hidden');
      call.removeAttribute('href');
      phone.textContent = '';
    }
    function refresh() {
      stop();
      var current = version;
      hideCall();
      status.textContent = 'در حال دریافت شمارهٔ پشتیبانی…';
      retry.disabled = true;
      controller = new AbortController();
      timer = setTimeout(function () { if (controller && current === version) controller.abort(); }, 10000);
      fetch('/api/config', { cache: 'no-store', signal: controller.signal }).then(function (response) {
        if (!response.ok) throw new Error('config_unavailable');
        return response.json();
      }).then(function (config) {
        if (current !== version || !dialog.open) return;
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
      }).catch(function () {
        if (current !== version || !dialog.open) return;
        hideCall();
        status.textContent = 'شمارهٔ پشتیبانی دریافت نشد. دوباره تلاش کنید.';
      }).finally(function () {
        if (current !== version) return;
        clearTimeout(timer);
        controller = null;
        retry.disabled = false;
      });
    }
    ['btn-safety-support', 'btn-quick-support', 'btn-sos'].forEach(function (id) {
      var button = document.getElementById(id);
      if (button) button.addEventListener('click', function () {
        if (dialog.open) return;
        dialog.showModal();
        close.focus();
        refresh();
      });
    });
    retry.addEventListener('click', refresh);
    close.addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('close', function () { if (!dialog.open) { stop(); hideCall(); } });
  });
})();
