'use strict';
/* تست واحد لایه‌ی پیامک (lib/sms.js) — بدون شبکه و بدون سرور:
 *   node test/sms.test.js
 * پیکربندی، تبدیل شماره و ساختن درخواست درست برای هر ارائه‌دهنده با fetch جعلی بررسی می‌شود. */
const { smsConfig, isConfigured, toReceptor, createSmsSender } = require('../lib/sms');

let passed = 0, failed = 0;
function check(name, ok, extra = '') {
  if (ok) { passed++; console.log('  ok   ' + name); }
  else { failed++; console.log('  FAIL ' + name + (extra ? '  [' + extra + ']' : '')); }
}
const okRes = (json) => async () => ({ ok: true, status: 200, json: async () => json });

async function expectThrow(name, p, code) {
  try { await p; check(name, false, 'no throw'); }
  catch (e) { check(name, e && e.code === code, e && (e.code + ' ' + e.message)); }
}

async function main() {
  console.log('== پیکربندی پیامک');
  check('بدون متغیر محیطی، پیکربندی خالی است', smsConfig({}).provider === '' && !isConfigured(smsConfig({})));
  check('کاوه‌نگار بدون کلید کامل نیست', !isConfigured(smsConfig({ HZ_SMS_PROVIDER: 'kavenegar' })));
  check('کاوه‌نگار با کلید کامل است', isConfigured(smsConfig({ HZ_SMS_PROVIDER: 'kavenegar', HZ_SMS_API_KEY: 'K' })));
  check('وب‌هوک با آدرس کامل است', isConfigured(smsConfig({ HZ_SMS_PROVIDER: 'webhook', HZ_SMS_WEBHOOK_URL: 'https://x.example/hook' })));
  check('قالب پیش‌فرض hamrah-otp است', smsConfig({}).template === 'hamrah-otp');

  console.log('== تبدیل شماره');
  check('شماره‌ی ایرانی به 09 تبدیل می‌شود', toReceptor('9123456789') === '09123456789');
  check('شماره‌ی بین‌المللی دست نمی‌خورد', toReceptor('+9647700000000') === '+9647700000000');

  console.log('== ارسال');
  const off = createSmsSender({});
  check('بدون پیکربندی، configured نادرست است', off.configured === false);
  await expectThrow('بدون پیکربندی، ارسال خطای not_configured می‌دهد', off.send('9123456789', '123456'), 'not_configured');

  // کاوه‌نگار: آدرس و پارامترهای درست
  let seenUrl = null;
  const kav = createSmsSender(
    { HZ_SMS_PROVIDER: 'kavenegar', HZ_SMS_API_KEY: 'KEY123', HZ_SMS_TEMPLATE: 'hamrah-otp' },
    async (url) => { seenUrl = url; return { ok: true, status: 200, json: async () => ({ return: { status: 200 } }) }; },
  );
  check('کاوه‌نگار با کلید، configured است', kav.configured === true);
  const r1 = await kav.send('9123456789', '654321');
  check('کاوه‌نگار ارسال موفق برمی‌گرداند', r1.provider === 'kavenegar' && r1.receptor === '09123456789');
  check('آدرس کاوه‌نگار شامل گیرنده، کد و قالب است',
    seenUrl === 'https://api.kavenegar.com/v1/KEY123/verify/lookup.json?receptor=09123456789&token=654321&template=hamrah-otp', seenUrl);
  await expectThrow('کاوه‌نگار به شماره‌ی خارجی خطای unsupported_phone می‌دهد', kav.send('+9647700000000', '123456'), 'unsupported_phone');
  const kavBad = createSmsSender({ HZ_SMS_PROVIDER: 'kavenegar', HZ_SMS_API_KEY: 'K' },
    async () => ({ ok: false, status: 401, json: async () => ({}) }));
  await expectThrow('پاسخ خطای کاوه‌نگار send_failed می‌شود', kavBad.send('9123456789', '123456'), 'send_failed');
  const kavNet = createSmsSender({ HZ_SMS_PROVIDER: 'kavenegar', HZ_SMS_API_KEY: 'K' },
    async () => { throw new Error('socket hangup'); });
  await expectThrow('خطای شبکه send_failed می‌شود', kavNet.send('9123456789', '123456'), 'send_failed');

  // وب‌هوک: بدنه‌ی JSON و سربرگ توکن
  let hook = null;
  const wh = createSmsSender(
    { HZ_SMS_PROVIDER: 'webhook', HZ_SMS_API_KEY: 'SECRET', HZ_SMS_WEBHOOK_URL: 'https://sms.example/send' },
    async (url, opts) => { hook = { url, opts }; return { ok: true, status: 200, json: async () => ({}) }; },
  );
  const r2 = await wh.send('9123456789', '112233');
  check('وب‌هوک ارسال موفق برمی‌گرداند', r2.provider === 'webhook');
  const body = JSON.parse(hook.opts.body);
  check('بدنه‌ی وب‌هوک شماره و کد دارد', body.phone === '09123456789' && body.code === '112233', hook.opts.body);
  check('وب‌هوک توکن Bearer می‌فرستد', hook.opts.headers.Authorization === 'Bearer SECRET');
  const whBad = createSmsSender({ HZ_SMS_PROVIDER: 'webhook', HZ_SMS_WEBHOOK_URL: 'https://x.example' },
    async () => ({ ok: false, status: 500, json: async () => ({}) }));
  await expectThrow('پاسخ ۵۰۰ وب‌هوک send_failed می‌شود', whBad.send('9123456789', '123456'), 'send_failed');

  console.log(`\nنتیجه: ${passed} موفق، ${failed} ناموفق`);
  process.exit(failed ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(1); });
