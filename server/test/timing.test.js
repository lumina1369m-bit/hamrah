'use strict';
// تست زمان‌بندی تطبیق روی سروری که با HZ_TIME_SCALE=0.01 بالا آمده (۶۰ ثانیه ≈ ۰٫۶ ثانیه، ۱۰ دقیقه ≈ ۶ ثانیه).
const BASE = process.env.BASE || 'http://127.0.0.1:8082';
let passed = 0, failed = 0;
const check = (name, ok, extra = '') => { if (ok) { passed++; console.log('  ok   ' + name); } else { failed++; console.log('  FAIL ' + name + (extra ? '  [' + extra + ']' : '')); } };
async function call(method, p, body, token) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(BASE + p, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = null; try { data = await r.json(); } catch (e) {}
  return { status: r.status, data };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function makeTranslator(phone) {
  await call('POST', '/api/auth/request-code', { phone, role: 'translator' });
  const v = await call('POST', '/api/auth/verify', { phone, role: 'translator', code: '123456' });
  await call('POST', '/api/dev/approve-translator', null, v.data.token);
  await call('PATCH', '/api/translator/online', { online: true }, v.data.token);
  return v.data.token;
}
async function main() {
  const k = String(Math.floor(Math.random() * 9e7) + 1e7); // ۸ رقم؛ شماره = '9' + k + n (۱۰ رقم)
  const A = await makeTranslator('9' + k + '1');
  await sleep(50);
  const B = await makeTranslator('9' + k + '2');
  await call('POST', '/api/auth/request-code', { phone: '9' + k + '3', role: 'traveler' });
  const pv = await call('POST', '/api/auth/verify', { phone: '9' + k + '3', role: 'traveler', code: '123456' });
  const P = pv.data.token;
  console.log('== پیشنهاد ۶۰ ثانیه‌ای');
  const r = await call('POST', '/api/traveler/bookings', { kind: 'instant', origin_lang: 'ar', dest_lang: 'fa', place: 'زمان‌بندی', traveler_name: 'T' }, P);
  const bid = r.data.id;
  let oa = await call('GET', '/api/translator/offers', null, A);
  let ob = await call('GET', '/api/translator/offers', null, B);
  const firstIsA = oa.data.offers.some((o) => o.place === 'زمان‌بندی');
  const firstIsB = ob.data.offers.some((o) => o.place === 'زمان‌بندی');
  check('پیشنهاد به یک مترجم رسید', firstIsA !== firstIsB);
  // مهلت پذیرش ۰٫۶ ثانیه است؛ بعد از آن پیشنهاد به نفر بعد می‌رود که مهلتش ۰٫۶ ثانیه‌ی دیگر است.
  // باید بین این دو باشیم: ۰٫۹ ثانیه (اگر بیشتر صبر کنیم، پیشنهاد دوم هم منقضی شده است)
  await sleep(900);
  oa = await call('GET', '/api/translator/offers', null, A);
  ob = await call('GET', '/api/translator/offers', null, B);
  const nowA = oa.data.offers.some((o) => o.place === 'زمان‌بندی');
  const nowB = ob.data.offers.some((o) => o.place === 'زمان‌بندی');
  check('پس از انقضا، پیشنهاد به مترجم دوم رفت', (firstIsA && nowB) || (firstIsB && nowA), JSON.stringify([nowA, nowB]));
  check('پس از انقضا، مترجم اول دیگر پیشنهاد ندارد', firstIsA ? !nowA : !nowB);
  console.log('== سقف جستجوی فوری ۱۰ دقیقه‌ای');
  await sleep(6500); // ≈ ۶ ثانیه سقف
  let bk = (await call('GET', '/api/traveler/bookings', null, P)).data.bookings.find((b) => b.id === bid);
  check('بعد از سقف، وضعیت «بدون تطبیق» است', bk.status === 'no_match', bk.status);
  const retry = await call('POST', `/api/traveler/bookings/${bid}/retry`, null, P);
  check('تلاش دوباره جستجو را از نو شروع می‌کند', retry.status === 200);
  bk = (await call('GET', '/api/traveler/bookings', null, P)).data.bookings.find((b) => b.id === bid);
  check('پس از تلاش دوباره وضعیت «در جستجو»', bk.status === 'searching');
  console.log('== زمان‌دار: قبل از پنجره‌ی تطبیق منتظر می‌ماند');
  const sched = new Date(Date.now() + 90 * 1000).toISOString(); // با مقیاس ۰٫۰۱ حداقل فاصله ۷۲ ثانیه است
  const rs = await call('POST', '/api/traveler/bookings', { kind: 'scheduled', origin_lang: 'ar', dest_lang: 'fa', place: 'قرار', scheduled_at: sched, traveler_name: 'T' }, P);
  check('رزرو زمان‌دار با مقیاس زمانی پذیرفته شد', rs.status === 201, JSON.stringify(rs));
  check('قبل از پنجره، هنوز پیشنهادی نیست (در انتظار)', rs.data.status === 'waiting_schedule');
  const cancelled = await call('POST', `/api/traveler/bookings/${rs.data.id}/cancel`, null, P);
  check('لغو زمان‌دار منتظر رایگان است', cancelled.status === 200 && cancelled.data.fee_percent === 0);
  console.log('== پنجره‌ی ۵ دقیقه‌ای درخواست تغییر (مقیاس ۰٫۰۱ ≈ ۳ ثانیه)');
  {
    const P2phone = '9' + k + '4';
    await call('POST', '/api/auth/request-code', { phone: P2phone, role: 'traveler' });
    const P2 = (await call('POST', '/api/auth/verify', { phone: P2phone, role: 'traveler', code: '123456' })).data.token;
    await call('POST', `/api/traveler/bookings/${bid}/cancel`, null, P);
    const place0 = 'مکان پنجره ' + k;
    const bk2 = (await call('POST', '/api/traveler/bookings', { kind: 'instant', origin_lang: 'ar', dest_lang: 'fa', place: place0, traveler_name: 'T' }, P2)).data;
    await sleep(100);
    const offA = (await call('GET', '/api/translator/offers', null, A)).data.offers || [];
    const offB = (await call('GET', '/api/translator/offers', null, B)).data.offers || [];
    const [tokOwner, offer] = offA.some((o) => o.place === place0) ? [A, offA.find((o) => o.place === place0)] : [B, offB.find((o) => o.place === place0)];
    const acc = await call('POST', `/api/translator/offers/${offer.id}/accept`, null, tokOwner);
    check('مترجم پیشنهاد را پذیرفت', acc.status === 200, JSON.stringify(acc));
    const ch = await call('POST', `/api/traveler/bookings/${bk2.id}/change`, { place: 'مکان جدید پنجره' }, P2);
    check('تغییر مکان پس از پذیرش، ۲۰۲ و در انتظار است', ch.status === 202 && ch.data.pending === true, JSON.stringify(ch));
    const dup = await call('POST', `/api/traveler/bookings/${bk2.id}/change`, { place: 'باز هم' }, P2);
    check('درخواست دوم هم‌زمان ممنوع است', dup.status === 409 && dup.data.error === 'change_pending');
    let view = (await call('GET', '/api/traveler/bookings', null, P2)).data.bookings.find((b) => b.id === bk2.id);
    check('در نمای مسافر، درخواست باز دیده می‌شود', !!view.pending_change);
    await sleep(3600); // ۵ دقیقه ≈ ۳ ثانیه با مقیاس؛ کمی بیشتر
    view = (await call('GET', '/api/traveler/bookings', null, P2)).data.bookings.find((b) => b.id === bk2.id);
    check('پس از پنجره، درخواست بی‌پاسخ منقضی و پاک می‌شود', view.pending_change === null, JSON.stringify(view.pending_change));
    check('مکان بدون پاسخ مترجم عوض نشده', view.place === place0, view.place);
    const late = await call('POST', `/api/translator/changes/${ch.data.id}/accept`, null, tokOwner);
    check('پذیرش دیرهنگام مترجم رد می‌شود', late.status === 410, String(late.status));
    const again = await call('POST', `/api/traveler/bookings/${bk2.id}/change`, { place: 'مکان جدید پنجره' }, P2);
    check('پس از انقضا، درخواست تازه مجاز است (شمارش ۲ از ۳)', again.status === 202, JSON.stringify(again));
    await call('POST', `/api/traveler/bookings/${bk2.id}/cancel`, null, P2);
  }
  console.log('== پایان خدمت پیش از زمان قرار ممنوع است');
  {
    // رزرو زمان‌دار: با مقیاس ۰٫۰۱، قرار ۷۵ ثانیه‌ی دیگر است و پنجره‌ی تطبیق ۳۶ ثانیه مانده به قرار باز می‌شود.
    const sched = new Date(Date.now() + 75 * 1000).toISOString();
    const rs = await call('POST', '/api/traveler/bookings', { kind: 'scheduled', origin_lang: 'ar', dest_lang: 'fa', place: 'پایان زودهنگام', scheduled_at: sched, traveler_name: 'T' }, P);
    check('رزرو زمان‌دار برای آزمون پایان ساخته شد', rs.status === 201, JSON.stringify(rs));
    // صبر تا بازشدن پنجره‌ی تطبیق و رسیدن پیشنهاد (حداکثر ~۵۰ ثانیه)
    let offer = null, owner = null;
    for (let i = 0; i < 250 && !offer; i++) {
      const oa = (await call('GET', '/api/translator/offers', null, A)).data.offers || [];
      const ob = (await call('GET', '/api/translator/offers', null, B)).data.offers || [];
      if (oa.some((o) => o.place === 'پایان زودهنگام')) { offer = oa.find((o) => o.place === 'پایان زودهنگام'); owner = A; }
      else if (ob.some((o) => o.place === 'پایان زودهنگام')) { offer = ob.find((o) => o.place === 'پایان زودهنگام'); owner = B; }
      if (!offer) await sleep(200);
    }
    check('پیشنهاد در پنجره‌ی تطبیق رسید', !!offer);
    if (offer) {
      const acc = await call('POST', `/api/translator/offers/${offer.id}/accept`, null, owner);
      check('پذیرش در پنجره ممکن است', acc.status === 200, JSON.stringify(acc));
      const fin = await call('POST', `/api/translator/missions/${rs.data.id}/finish`, null, owner);
      check('پایان خدمت پیش از زمان قرار: ۴۰۹', fin.status === 409 && fin.data.error === 'too_early', JSON.stringify(fin));
    }
    await call('POST', `/api/traveler/bookings/${rs.data.id}/cancel`, null, P);
  }
  console.log(`\nنتیجه: ${passed} موفق، ${failed} ناموفق`);
  process.exit(failed ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(1); });
