/* Server-backed translator settings for which passenger genders may receive new offers. */
(function () {
  'use strict';
  var select = document.getElementById('translator-traveler-gender-pref');
  var saveButton = document.getElementById('translator-gender-pref-save');
  var status = document.getElementById('translator-gender-pref-status');
  if (!select || !saveButton || !status) return;

  var choices = ['any', 'male', 'female'];
  var revision = 0, busy = false;
  function token() { return window.HZ.load().token || null; }
  function say(message, error) {
    status.textContent = message;
    status.classList.toggle('text-error', !!error);
  }
  function controls(disabled) {
    select.disabled = disabled;
    saveButton.disabled = disabled;
  }
  async function request(method, actor, body) {
    var controller = new AbortController(), timer;
    try {
      var timeout = new Promise(function (_, reject) {
        timer = setTimeout(function () { controller.abort(); reject(new Error('timeout')); }, 10000);
      });
      var response = await Promise.race([fetch('/api/translator/preferences', {
        method: method,
        cache: 'no-store',
        signal: controller.signal,
        headers: window.HZ.authHeaders(actor, { 'Content-Type': 'application/json' }),
        body: body === undefined ? undefined : JSON.stringify(body)
      }), timeout]);
      var data = await response.json().catch(function () { return null; });
      if (!response.ok) throw new Error(data && data.error || 'unavailable');
      return data;
    } finally {
      clearTimeout(timer);
      controller.abort();
    }
  }
  async function refresh() {
    if (busy) return;
    var read = ++revision, actor = token();
    controls(true);
    if (!actor) { say('برای دریافت تنظیمات دوباره وارد شوید.', true); return; }
    say('در حال دریافت تنظیم از سرور…');
    try {
      var data = await request('GET', actor);
      if (read !== revision || token() !== actor) return;
      if (!data || !choices.includes(data.traveler_gender_pref)) throw new Error('invalid');
      select.value = data.traveler_gender_pref;
      controls(false);
      say('تنظیم فعلی از سرور دریافت شد.');
    } catch (_) {
      if (read === revision && token() === actor) say('تنظیم دریافت نشد؛ اتصال را بررسی و دوباره وارد شوید.', true);
    }
  }
  async function save() {
    if (busy) return;
    var actor = token(), value = select.value, read = ++revision;
    if (!actor || !choices.includes(value)) { say('نشست یا انتخاب تنظیم معتبر نیست.', true); return; }
    busy = true; controls(true); say('در حال ذخیرهٔ تنظیم روی سرور…');
    try {
      var data = await request('PATCH', actor, { traveler_gender_pref: value });
      if (read !== revision || token() !== actor) return;
      if (!data || data.ok !== true || data.traveler_gender_pref !== value) throw new Error('invalid');
      say('تنظیم ذخیره شد و برای پیشنهادهای جدید اعمال می‌شود.');
    } catch (_) {
      if (read === revision && token() === actor) say('ذخیره انجام نشد؛ تنظیم قبلی روی سرور باقی مانده است.', true);
    } finally {
      busy = false;
      if (read === revision) controls(!token());
    }
  }

  saveButton.addEventListener('click', save);
  window.addEventListener('storage', refresh);
  refresh();
  window.HZ_TRANSLATOR_SETTINGS = { refresh: refresh };
})();
