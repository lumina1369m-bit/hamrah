# تست میز کار مترجم: پذیرش ← پایان خدمت ← مسافر نقدی ثبت می‌کند ← مترجم دریافت را تأیید می‌کند ← رزرو «انجام‌شده».
import asyncio, re, random, sys, urllib.request
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS

BASE = 'http://127.0.0.1:8081'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

urllib.request.urlopen(urllib.request.Request(BASE + '/api/dev/offline-all', method='POST'), timeout=10).read()

TRAV_LOGIN = """async (phone) => {
  const H = {'Content-Type': 'application/json'};
  await fetch('/api/auth/request-code', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler'})});
  const v = await (await fetch('/api/auth/verify', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler', code:'123456'})})).json();
  localStorage.setItem('hamzaban.token.v1', v.token);
  return v.token;
}"""
API = """async ([method, path, body, token]) => {
  const r = await fetch('/api' + path, {method, headers:{'Content-Type':'application/json', Authorization:'Bearer '+token}, body: body ? JSON.stringify(body) : undefined});
  let d = null; try { d = await r.json(); } catch (e) {}
  return {status: r.status, data: d};
}"""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        async def route(ctx):
            await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        tctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(tctx)
        T = await tctx.new_page(); terr = []; T.on('pageerror', lambda e: terr.append(str(e)[:120]))
        await T.goto(BASE + '/translator/index.html'); await T.wait_for_timeout(600)
        await T.evaluate(LOGIN_JS, '9' + str(random.randint(100000000, 999999999)))
        ttok = await T.evaluate("()=>HZ.load().token")
        await T.evaluate("async (t)=>{await fetch('/api/translator/online',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},body:JSON.stringify({online:true})});}", ttok)
        # مسافر: رزرو فوری
        pctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(pctx)
        P = await pctx.new_page(); await P.goto(BASE + '/traveler/index.html'); await P.wait_for_timeout(400)
        ptok = await P.evaluate(TRAV_LOGIN, '9' + str(random.randint(100000000, 999999999)))
        place = 'میز کار پرداخت ' + str(random.randint(100, 999))
        bid = (await P.evaluate(API, ['POST', '/traveler/bookings', {'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa', 'place': place, 'traveler_name': 'علی رضایی'}, ptok]))['data']['id']
        # مترجم در میز کار: پذیرش پیشنهاد
        await T.goto(BASE + '/translator/app.html'); await T.wait_for_timeout(4500)
        ok_btn = await T.evaluate("()=>{const box=document.getElementById('offers-box'); const b=[...box.querySelectorAll('button')].find(x=>x.textContent.trim()==='پذیرش'); if(b){b.click(); return true;} return false;}")
        check('مترجم در میز کار پیشنهاد را پذیرفت', ok_btn)
        await T.wait_for_timeout(1500)
        await T.reload(); await T.wait_for_timeout(1200)
        # شروع خدمت با کد امنیتی مسافر از روی کارت ماموریت
        scode = next(x['service_code'] for x in (await P.evaluate(API, ['GET', '/traveler/bookings', None, ptok]))['data']['bookings'] if x['id'] == bid)
        started = await T.evaluate("""(code)=>{const inp=document.querySelector('#missions-list input'); if(!inp) return false; inp.value=code; const b=[...document.querySelectorAll('#missions-list button')].find(x=>x.textContent.trim()==='ثبت کد و شروع خدمت'); if(!b) return false; b.click(); return true;}""", scode)
        check('شروع خدمت با کد امنیتی از میز کار', started)
        await T.wait_for_timeout(1500); await T.reload(); await T.wait_for_timeout(1200)
        check('دکمه‌ی «پایان خدمت» روی ماموریت است', await T.evaluate("()=>[...document.querySelectorAll('#missions-list button')].some(x=>x.textContent.trim()==='پایان خدمت')"))
        await T.evaluate("()=>{const b=[...document.querySelectorAll('#missions-list button')].find(x=>x.textContent.trim()==='پایان خدمت'); b && b.click();}")
        await T.wait_for_timeout(1500)
        await T.reload(); await T.wait_for_timeout(1200)
        # مسافر روش نقدی را انتخاب می‌کند
        await P.evaluate(API, ['POST', f'/traveler/bookings/{bid}/payment', {'method': 'cash'}, ptok])
        await T.wait_for_timeout(5500)
        check('بخش پرداخت منتظر تأیید نمایش داده می‌شود', await T.evaluate("()=>!!document.getElementById('payments-box') && document.getElementById('payments-box').textContent.includes('دریافت وجه را تأیید می‌کنم')"))
        await T.evaluate("()=>{const b=[...document.querySelectorAll('#payments-box button')].find(x=>x.textContent.trim()==='دریافت وجه را تأیید می‌کنم'); b && b.click();}")
        await T.wait_for_timeout(1500)
        st = (await P.evaluate(API, ['GET', '/traveler/bookings', None, ptok]))['data']['bookings']
        bk = next(x for x in st if x['id'] == bid)
        check('با تأیید مترجم، رزرو انجام‌شده و تسویه است', bk['status'] == 'done' and bk['pay_state'] == 'settled')
        check('خطای صفحه‌ها', not terr)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})', terr if terr else '')
        sys.exit(0 if ok else 1)

asyncio.run(main())
