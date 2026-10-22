# تست دکمه‌ی «تسویه و بازگشت» در اپ مسافر: روی سرور ثبت می‌شود (نقدی: awaiting_cash، آنلاین: settled)
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
    urllib.request.urlopen(urllib.request.Request(BASE + '/api/dev/offline-all', method='POST'), timeout=10).read()

async def make_finished(b, route, method):
    reset_presence()  # مترجم دور قبل نباید پیشنهاد را بگیرد
    tctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(tctx)
    T = await tctx.new_page(); await T.goto(BASE + '/translator/index.html'); await T.wait_for_timeout(600)
    tphone = '9' + str(random.randint(100000000, 999999999))
    await T.evaluate(LOGIN_JS, tphone)
    ttok = await T.evaluate("()=>HZ.load().token")
    await T.evaluate("async (t)=>{await fetch('/api/translator/online',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},body:JSON.stringify({online:true})});}", ttok)
    pctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(pctx)
    P = await pctx.new_page(); perr = []; P.on('pageerror', lambda e: perr.append(str(e)[:120]))
    await P.goto(BASE + '/traveler/index.html'); await P.wait_for_timeout(500)
    await P.evaluate(TRAV_LOGIN, '9' + str(random.randint(100000000, 999999999)))
    await P.goto(BASE + '/traveler/app.html'); await P.wait_for_timeout(1200)
    ptok = await P.evaluate("()=>localStorage.getItem('hamzaban.token.v1')")
    place = 'تسویه UI ' + method + ' ' + str(random.randint(100, 999))
    created = await P.evaluate(API, ['POST', '/traveler/bookings', {'kind':'instant','origin_lang':'ar','dest_lang':'fa','place':place,'traveler_name':'علی رضایی'}, ptok])
    bid = created['data']['id']
    await T.wait_for_timeout(1200)
    off = await T.evaluate(API, ['GET', '/translator/offers', None, ttok])
    o = next((x for x in off['data']['offers'] if x['place'] == place), None)
    if o:
        await T.evaluate(API, ['POST', f"/translator/offers/{o['id']}/accept", None, ttok])
        await T.evaluate(API, ['POST', f'/translator/missions/{bid}/verify-code', {'code': created['data']['service_code']}, ttok])
        requested = await T.evaluate(API, ['POST', f'/translator/missions/{bid}/finish', None, ttok])
        assert requested['status'] == 202, requested
        approved = await P.evaluate(API, ['POST', f'/traveler/bookings/{bid}/finish-approve', None, ptok])
        assert approved['status'] == 200, approved
    await P.wait_for_timeout(6500)
    return P, ptok, bid, bool(o), perr

async def main():
    async with async_playwright() as p:
        reset_presence()
        b = await p.chromium.launch(args=['--no-sandbox'])
        async def route(ctx):
            await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        # پرداخت آنلاین پیش‌فرض خاموش است؛ برای این تست از مدیر روشن و در پایان برمی‌گردانیم
        import json
        def admin(method_, path, body=None, token=None):
            h = {'Content-Type': 'application/json'}
            if token: h['Authorization'] = 'Bearer ' + token
            rq = urllib.request.Request(BASE + path, method=method_, headers=h, data=json.dumps(body).encode() if body is not None else None)
            return json.loads(urllib.request.urlopen(rq, timeout=10).read() or b'{}')
        atok = admin('POST', '/api/admin/login', {'password': 'test-admin-pass'}).get('token')
        admin('PUT', '/api/admin/settings', {'online_enabled': 1}, atok)
        check('پرداخت آنلاین برای تست روشن شد', atok is not None)
        for method in ['cash', 'online']:
            P, ptok, bid, matched, perr = await make_finished(b, route, method)
            check(f'[{method}] مترجم پیشنهاد را دید و پایان داد', matched)
            # دکمه‌ی تسویه را با روش انتخابی فعال می‌کنیم
            await P.evaluate("(m)=>{ window.payChoice = m; document.getElementById('btn-settle-return').click(); }", method)
            await P.wait_for_timeout(1200)
            st = await P.evaluate(API, ['GET', '/traveler/bookings', None, ptok])
            bk = next(x for x in st['data']['bookings'] if x['id'] == bid)
            if method == 'cash':
                check('[cash] سرور پرداخت نقدی را ثبت کرد (awaiting_cash)', bk['pay_state'] == 'awaiting_cash')
            else:
                check('[online] سرور پرداخت آنلاین را تسویه کرد (done/settled)', bk['status'] == 'done' and bk['pay_state'] == 'settled')
            check(f'[{method}] خطای صفحه‌ها', not perr)
        admin('PUT', '/api/admin/settings', {'online_enabled': 0}, atok)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})')
        sys.exit(0 if ok else 1)

asyncio.run(main())
