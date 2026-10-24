
// امکانات از سرور (پنل مدیر): خاموش‌بودن هر امکان، بخش مربوط را در میز کار پنهان می‌کند
(function () {
  function show(el, on) { if (el) el.style.display = on ? '' : 'none'; }
  fetch('/api/config').then(function (r) { return r.json(); }).then(function (d) {
    var f = d.features || {};
    if (f.translator_online === false) {
      var t = document.querySelector('[aria-label="تغییر وضعیت آماده به خدمت"]');
      if (t) show(t, false);
    }
    if (f.interview_scheduling === false) show(document.getElementById('iv-box'), false);
  }).catch(function () {});
})();
