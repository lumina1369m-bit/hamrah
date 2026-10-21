# تست رابط تغییر رزرو: مسافر پس از پذیرش مترجم، مکان را عوض می‌کند؛ مترجم کارت را می‌بیند و می‌پذیرد؛ مسافر نتیجه را می‌بیند.
import asyncio, re, random, sys
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS

BASE = 'http://127.0.0.1:8081'
TRAV_LOGIN = """async (phone) => {
  const H = {'Content-Type': 'application/json'};
  await fetch('/api/auth/request-code', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler'})});
  const v = await (await fetch('/api/auth/verify', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler', code:'123456'})})).json();
  localStorage.setItem('hamzaban.token.v1', v.token);
  localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'علی', last:'رضایی', gender:'مرد', phone}));
  return v.token;
}"""

results = []
def check(name, ok):
    results.append(ok)
    print(('  ok   ' if ok else '  FAIL ') + name)

async def open_live(P):
    await P.evaluate("()=>document.querySelector('nav a[data-nav=bookings]').click()")
    await P.wait_for_timeout(500)
    await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-tabs button')].find(x=>x.textContent.trim()==='در جریان'); if(b) b.click();}")
    await P.wait_for_timeout(300)

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
        tctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(tctx)
        T = await tctx.new_page(); terr = []; T.on('pageerror', lambda e: terr.append(str(e)[:120]))
        await T.goto(BASE + '/translator/index.html'); await T.wait_for_timeout(600)
        tphone = '9' + str(random.randint(100000000, 999999999))
        await T.evaluate(LOGIN_JS, tphone)
        await T.evaluate("async()=>{const t=HZ.load().token; await fetch('/api/translator/online',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},body:JSON.stringify({online:true})});}")

        pctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(pctx)
        P = await pctx.new_page(); perr = []; P.on('pageerror', lambda e: perr.append(str(e)[:120]))
        await P.goto(BASE + '/traveler/index.html'); await P.wait_for_timeout(500)
        await P.evaluate(TRAV_LOGIN, '9' + str(random.randint(100000000, 999999999)))
        await P.goto(BASE + '/traveler/app.html'); await P.wait_for_timeout(1200)
        place = 'مکان اولیه ' + str(random.randint(100, 999))
        new_place = 'مکان جدید ' + str(random.randint(100, 999))
        created = await P.evaluate("""async (place)=>{const t=localStorage.getItem('hamzaban.token.v1');
            const r=await fetch('/api/traveler/bookings',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},
              body:JSON.stringify({kind:'instant',origin_lang:'ar',dest_lang:'fa',place,traveler_name:'علی رضایی'})});
            return {status:r.status, body: await r.json()};}""", place)
        check('رزرو فوری ساخته شد', created['status'] == 201)

        # مترجم پیشنهاد را می‌پذیرد
        await T.goto(BASE + '/translator/app.html'); await T.wait_for_timeout(4500)
        await T.evaluate("""()=>{const box=document.getElementById('offers-box'); const btn=[...box.querySelectorAll('button')].find(b=>b.textContent.trim()==='پذیرش'); btn && btn.click();}""")
        await T.wait_for_timeout(1500)

        # مسافر: پس از همگام‌سازی، دکمه‌ی «تغییر» باید باشد
        await P.wait_for_timeout(6500)
        await P.reload(); await P.wait_for_timeout(1200)
        await open_live(P)
        has_change_btn = await P.evaluate("()=>[...document.querySelectorAll('#bk-list button')].some(x=>x.textContent.trim()==='تغییر')")
        check('دکمه‌ی «تغییر» برای رزرو تطبیق‌یافته دیده می‌شود', has_change_btn)

        # مسافر مکان را تغییر می‌دهد
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-list button')].find(x=>x.textContent.trim()==='تغییر'); b && b.click();}")
        await P.wait_for_timeout(400)
        await P.fill('#bk-modal input[type=text]', new_place)
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-modal button')].find(x=>x.textContent.trim()==='ثبت تغییر'); b && b.click();}")
        await P.wait_for_timeout(1200)
        pend_text = await P.evaluate("()=>document.getElementById('bk-list').textContent")
        check('متن انتظار پاسخ مترجم روی کارت دیده می‌شود', 'در انتظار پاسخ مترجم' in pend_text)

        # مترجم کارت تغییر را می‌بیند و می‌پذیرد
        await T.wait_for_timeout(3500)
        box_text = await T.evaluate("()=>document.getElementById('offers-box').textContent")
        check('مترجم کارت درخواست تغییر را می‌بیند', new_place in box_text)
        await T.evaluate("""()=>{const box=document.getElementById('offers-box'); const btn=[...box.querySelectorAll('button')].find(b=>b.textContent.trim()==='پذیرش'); btn && btn.click();}""")
        await T.wait_for_timeout(1500)

        # مسافر نتیجه را می‌بیند
        await P.wait_for_timeout(6500)
        await P.reload(); await P.wait_for_timeout(1200)
        await open_live(P)
        final_text = await P.evaluate("()=>document.getElementById('bk-list').textContent")
        check('پس از پذیرش مترجم، مکان جدید روی کارت است', new_place in final_text)
        check('پس از پذیرش، پیام انتظار حذف شده است', 'در انتظار پاسخ مترجم' not in final_text)

        # تبدیل به زمان‌دار: یک رزرو فوری بدون مترجم
        check('خطای صفحه‌ها', not terr and not perr)
        if terr or perr: print('  errors:', terr + perr)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})')
        sys.exit(0 if ok else 1)

asyncio.run(main())
