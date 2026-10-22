# تست فاکتور رزرو انجام‌شده‌ی سرور در اپ مسافر: مبلغ کل از سرور، روش پرداخت، بدون صفر شدن مبلغ
import asyncio, re, random, sys, json, urllib.request
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

def admin(method_, path, body=None, token=None):
    h = {'Content-Type': 'application/json'}
    if token: h['Authorization'] = 'Bearer ' + token
    rq = urllib.request.Request(BASE + path, method=method_, headers=h, data=json.dumps(body).encode() if body is not None else None)
    return json.loads(urllib.request.urlopen(rq, timeout=10).read() or b'{}')

def fa(x):
    return str(x).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

async def main():
    atok = admin('POST', '/api/admin/login', {'password': 'test-admin-pass'}).get('token')
    admin('PUT', '/api/admin/settings', {'online_enabled': 1}, atok)
    admin('POST', '/api/dev/offline-all')
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        async def route(ctx):
            await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
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
        place = 'فاکتور UI ' + str(random.randint(100, 999))
        created = await P.evaluate(API, ['POST', '/traveler/bookings', {'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa', 'place': place, 'traveler_name': 'علی رضایی'}, ptok])
        bid = created['data']['id']
        await T.wait_for_timeout(1200)
        off = await T.evaluate(API, ['GET', '/translator/offers', None, ttok])
        o = next((x for x in off['data']['offers'] if x['place'] == place), None)
        check('مترجم پیشنهاد را دید', o is not None)
        if o:
            await T.evaluate(API, ['POST', f"/translator/offers/{o['id']}/accept", None, ttok])
            await T.evaluate(API, ['POST', f'/translator/missions/{bid}/finish', None, ttok])
        await P.wait_for_timeout(6500)
        # پرداخت آنلاین: رزرو به «انجام‌شده» (settled) می‌رسد
        await P.evaluate("()=>{ window.payChoice = 'online'; document.getElementById('btn-settle-return').click(); }")
        await P.wait_for_timeout(1500)
        st = await P.evaluate(API, ['GET', '/traveler/bookings', None, ptok])
        bk = next(x for x in st['data']['bookings'] if x['id'] == bid)
        total = bk['total']
        check('سرور رزرو را انجام‌شده و تسویه‌شده ثبت کرد', bk['status'] == 'done' and bk['pay_state'] == 'settled')
        # فهرست رزروها: برگه‌ی انجام‌شده
        await P.reload(); await P.wait_for_timeout(1200)
        await P.locator('nav a[data-nav=bookings]').first.click(); await P.wait_for_timeout(900)
        await P.locator('#bk-tabs button', has_text='انجام').first.click(); await P.wait_for_timeout(600)
        card = P.locator('#bk-list > *', has_text=place).first
        await P.wait_for_timeout(300)
        check('رزرو انجام‌شده در فهرست است', await card.count() == 1)
        await card.get_by_role('button', name='فاکتور', exact=True).first.click(); await P.wait_for_timeout(1200)
        modal = await P.evaluate("()=>document.body.innerText")
        check('فاکتور باز شد', 'فاکتور رزرو' in modal)
        check('مبلغ کل فاکتور از سرور است (صفر نیست)', fa(total) in modal or (total > 0 and fa(f'{total:,}') in modal))
        check('فاکتور خدمت (قبل از مالیات) و مالیات را جدا نشان می‌دهد', 'خدمت همراهی' in modal and 'مالیات و خدمات رفاهی' in modal)
        check('روش پرداخت آنلاین نشان داده می‌شود', 'آنلاین' in modal)
        check('وضعیت پرداخت «تسویه شده» است', 'تسویه شده' in modal)
        check('خطای صفحه', not perr)
        await b.close()
    admin('PUT', '/api/admin/settings', {'online_enabled': 0}, atok)
    ok = all(results)
    print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})')
    sys.exit(0 if ok else 1)

asyncio.run(main())
