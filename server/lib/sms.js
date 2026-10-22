'use strict';
// لایه‌ی ارسال پیامک کد یک‌بارمصرف (OTP).
// هنوز شرکت پیامک انتخاب نشده است؛ این ماژول طوری ساخته شده که با تنظیم متغیرهای محیطی فعال شود
// و نیازی به تغییر کد نباشد:
//
//   HZ_SMS_PROVIDER   نام ارائه‌دهنده: 'kavenegar' یا 'webhook' (خالی = پیامک غیرفعال)
//   HZ_SMS_API_KEY    کلید API ارائه‌دهنده (برای webhook: توکن Bearer اختیاری)
//   HZ_SMS_TEMPLATE   نام قالب پیامک در پنل کاوه‌نگار که جای‌نگهدار کد دارد (پیش‌فرض: hamrah-otp)
//   HZ_SMS_WEBHOOK_URL آدرس وب‌هوک برای حالت webhook؛ بدنه‌ی JSON { phone, code } پست می‌شود
//
// در حالت توسعه (HZ_DEV=1) از این ماژول استفاده نمی‌شود و کد ثابت توسعه به کار می‌رود.
// خطاها با ویژگی code برگردانده می‌شوند: 'not_configured' | 'send_failed' | 'unsupported_phone'.

function smsConfig(env) {
  const e = env || {};
  return {
    provider: String(e.HZ_SMS_PROVIDER || '').trim().toLowerCase(),
    apiKey: String(e.HZ_SMS_API_KEY || '').trim(),
    template: String(e.HZ_SMS_TEMPLATE || 'hamrah-otp').trim(),
    webhookUrl: String(e.HZ_SMS_WEBHOOK_URL || '').trim(),
  };
}

function isConfigured(cfg) {
  if (cfg.provider === 'kavenegar') return !!cfg.apiKey;
  if (cfg.provider === 'webhook') return !!cfg.webhookUrl;
  return false;
}

// شماره‌ی ذخیره‌شده‌ی ایرانی به شکل 9xxxxxxxxx است؛ بیشتر پنل‌های داخلی 09xxxxxxxxx می‌خواهند.
function toReceptor(phone) {
  const p = String(phone || '');
  if (/^9\d{9}$/.test(p)) return '0' + p;
  return p;
}

function fail(code, message) {
  const err = new Error(message || code);
  err.code = code;
  return err;
}

// سازنده‌ی فرستنده. fetchImpl برای تست قابل تزریق است.
function createSmsSender(env, fetchImpl) {
  const cfg = smsConfig(env);
  const doFetch = fetchImpl || globalThis.fetch;
  const configured = isConfigured(cfg);

  async function send(phone, code) {
    if (!configured) throw fail('not_configured', 'sms_provider_not_configured');
    const receptor = toReceptor(phone);
    // پنل‌های داخلی به شماره‌ی خارجی پیامک نمی‌فرستند؛ همان ابتدا روشن خطا می‌دهیم.
    if (cfg.provider === 'kavenegar' && !/^09\d{9}$/.test(receptor)) {
      throw fail('unsupported_phone', 'sms_unsupported_phone');
    }
    let res;
    try {
      if (cfg.provider === 'kavenegar') {
        const url = 'https://api.kavenegar.com/v1/' + encodeURIComponent(cfg.apiKey) + '/verify/lookup.json'
          + '?receptor=' + encodeURIComponent(receptor)
          + '&token=' + encodeURIComponent(String(code))
          + '&template=' + encodeURIComponent(cfg.template);
        res = await doFetch(url, { method: 'GET', signal: AbortSignal.timeout(8000) });
        if (!res.ok) throw fail('send_failed', 'kavenegar http ' + res.status);
        const data = await res.json().catch(() => null);
        const status = data && data.return && data.return.status;
        if (status && status !== 200) throw fail('send_failed', 'kavenegar status ' + status);
      } else { // webhook
        res = await doFetch(cfg.webhookUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(cfg.apiKey ? { Authorization: 'Bearer ' + cfg.apiKey } : {}),
          },
          body: JSON.stringify({ phone: receptor, code: String(code) }),
          signal: AbortSignal.timeout(8000),
        });
        if (!res.ok) throw fail('send_failed', 'webhook http ' + res.status);
      }
    } catch (e) {
      if (e && e.code) throw e;
      throw fail('send_failed', 'sms network: ' + (e && e.message ? e.message : 'unknown'));
    }
    return { provider: cfg.provider, receptor };
  }

  return { configured, config: cfg, send };
}

module.exports = { smsConfig, isConfigured, toReceptor, createSmsSender };
