# تست پرداخت نقدی در اپ مسافر: رزرو پذیرفته‌شده → پایان خدمت (مترجم) → مسافر نقدی را ثبت می‌کند → مترجم تأیید می‌کند → «انجام‌شده».
import asyncio, re, random, sys
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

TRAV_LOGIN = """async (phone) => {
  const H = {'Content-Type': 'application/json'};
  await fetch('/api/auth/request-code', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler'})});
  const v = await (await fetch('/api/auth/verify', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler', code:'123456'})})).json();
  localStorage.setItem('hamzaban.token.v1', v.token);
  localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'علی', last:'رضایی', gender:'مرد', phone}));
  return v.token;
}"""

API = """async ([method, path, body, token]) => {
  const r = await fetch('/api' + path, {method, headers:{'Content-Type':'application/json', Authorization:'Bearer '+token}, body: body ? JSON.stringify(body) : undefined});
  let d = null; try { d = await r.json(); } catch (e) {}
  return {status: r.status, data: d};
}"""

import urllib.request
def reset_presence():
    # فقط حالت توسعه: مترجمان باقی‌مانده از تست‌های قبلی آفلاین شوند
    urllib.request.urlopen(urllib.request.Request(BASE + '/api/dev/offline-all', method='POST'), timeout=10).read()

async def main():
    async with async_playwright() as p:
        reset_presence()
        b = await p.chromium.launch(args=['--no-sandbox'])
        async def route(ctx):
            await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        # مترجم آنلاین
        tctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(tctx)
        T = await tctx.new_page(); await T.goto(BASE + '/translator/index.html'); await T.wait_for_timeout(600)
        tphone = '9' + str(random.randint(100000000, 999999999))
        await T.evaluate(LOGIN_JS, tphone)
        ttok = await T.evaluate("()=>HZ.load().token")
        await T.evaluate("async (t)=>{await fetch('/api/translator/online',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},body:JSON.stringify({online:true})});}", ttok)
        # مسافر
        pctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(pctx)
        P = await pctx.new_page(); perr = []; P.on('pageerror', lambda e: perr.append(str(e)[:120]))
        await P.goto(BASE + '/traveler/index.html'); await P.wait_for_timeout(500)
        await P.evaluate(TRAV_LOGIN, '9' + str(random.randint(100000000, 999999999)))
        await P.goto(BASE + '/traveler/app.html'); await P.wait_for_timeout(1200)
        ptok = await P.evaluate("()=>localStorage.getItem('hamzaban.token.v1')")
        place = 'پرداخت UI ' + str(random.randint(100, 999))
        created = await P.evaluate(API, ['POST', '/traveler/bookings', {'kind':'instant','origin_lang':'ar','dest_lang':'fa','place':place,'traveler_name':'علی رضایی'}, ptok])
        bid = created['data']['id']
        check('رزرو فوری ساخته شد', created['status'] == 201)
        # مترجم پذیرش و پایان خدمت
        await T.wait_for_timeout(1200)
        off = await T.evaluate(API, ['GET', '/translator/offers', None, ttok])
        o = next((x for x in off['data']['offers'] if x['place'] == place), None)
        check('مترجم پیشنهاد را دید', o is not None)
        if o:
            await T.evaluate(API, ['POST', f"/translator/offers/{o['id']}/accept", None, ttok])
            await T.evaluate(API, ['POST', f'/translator/missions/{bid}/verify-code', {'code': created['data']['service_code']}, ttok])
            await T.evaluate(API, ['POST', f'/translator/missions/{bid}/finish', None, ttok])
        # مسافر: همگام‌سازی و پرداخت نقدی
        await P.wait_for_timeout(6500)
        await P.evaluate("()=>document.querySelector('nav a[data-nav=bookings]').click()")
        await P.wait_for_timeout(500)
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-tabs button')].find(x=>x.textContent.trim()==='در جریان'); if(b) b.click();}")
        await P.wait_for_timeout(300)
        has_pay = await P.evaluate("()=>[...document.querySelectorAll('#bk-list button')].some(x=>x.textContent.trim()==='پرداخت')")
        check('پس از پایان خدمت، دکمه‌ی «پرداخت» دیده می‌شود', has_pay)
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-list button')].find(x=>x.textContent.trim()==='پرداخت'); b && b.click();}")
        await P.wait_for_timeout(700)
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-modal button')].find(x=>x.textContent.trim()==='نقدی پرداخت کردم'); b && b.click();}")
        await P.wait_for_timeout(1200)
        st = await P.evaluate(API, ['GET', '/traveler/bookings', None, ptok])
        bk = next(x for x in st['data']['bookings'] if x['id'] == bid)
        check('سرور پرداخت نقدی را ثبت کرد', bk['pay_state'] == 'awaiting_cash')
        # مترجم دریافت را تأیید می‌کند
        r = await T.evaluate(API, ['POST', f'/translator/missions/{bid}/cash-confirm', None, ttok])
        check('مترجم تأیید کرد و رزرو تسویه شد', r['status'] == 200 and r['data']['settled'] is True)
        await P.wait_for_timeout(6500)
        await P.evaluate("()=>document.querySelector('nav a[data-nav=bookings]').click()")
        await P.wait_for_timeout(500)
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-tabs button')].find(x=>x.textContent.trim()==='انجام‌شده'); if(b) b.click();}")
        await P.wait_for_timeout(300)
        done_text = await P.evaluate("()=>document.getElementById('bk-list').textContent")
        check('رزرو در برگه‌ی «انجام‌شده» است', place in done_text)
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-list button')].find(x=>x.textContent.trim()==='فاکتور'); b && b.click();}")
        await P.wait_for_timeout(500)
        inv = await P.evaluate("()=>{const m=document.getElementById('bk-modal'); return m ? m.textContent : '';}")
        check('فاکتور رزرو همگام‌شده کل قابل پرداخت را نشان می‌دهد', 'مبلغ کل قابل پرداخت' in inv and 'تومان' in inv)
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-modal button')].find(x=>x.textContent.trim()==='بستن'); b && b.click();}")
        check('خطای صفحه‌ها', not perr)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})', perr if perr else '')
        sys.exit(0 if ok else 1)

asyncio.run(main())
