# تست مرورگر: تعرفه‌ی مدیر در اپ مسافر و کارت‌های جفت‌زبان در اپ مترجم
# نیاز به سرور تست جدا دارد (پیش‌فرض ۸۰۹۰). مثال:
#   cd server && HZ_DEV=1 HZ_ADMIN_PASSWORD=test-admin-pass HZ_DB=/tmp/tb.sqlite PORT=8090 node server.js
import asyncio, sys, json, random, urllib.request
from playwright.async_api import async_playwright

TRAV_LOGIN = """async (phone) => {
  const H = {'Content-Type': 'application/json'};
  await fetch('/api/auth/request-code', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler'})});
  const v = await (await fetch('/api/auth/verify', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler', code:'123456'})})).json();
  localStorage.setItem('hamzaban.token.v1', v.token);
  localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'علی', last:'رضایی', gender:'مرد', phone}));
  return v.token;
}"""

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8090'
PASSWORD = 'test-admin-pass'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

def api(method, path, body=None, token=None):
    h = {'Content-Type': 'application/json'}
    if token: h['X-Admin-Token'] = token
    rq = urllib.request.Request(BASE + '/api' + path, method=method, headers=h,
                                data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(rq, timeout=10) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')

async def main():
    _, adm = api('POST', '/admin/login', {'password': PASSWORD})
    tok = adm['token']
    _, before = api('GET', '/admin/settings', token=tok)
    old_tariff = before['settings']['hourly_tariffs']['value']
    new_tariff = dict(old_tariff) if isinstance(old_tariff, dict) else json.loads(old_tariff)
    new_tariff['general'] = 1777000
    st, _ = api('PUT', '/admin/settings', {'hourly_tariffs': new_tariff}, token=tok)
    check('admin: تغییر نرخ عمومی ذخیره شد', st == 200)
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(args=['--no-sandbox'])
            # ---- مسافر: نرخ ساعتی از سرور
            pg = await b.new_page(viewport={'width': 390, 'height': 844})
            errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            await pg.goto(BASE + '/traveler/index.html', wait_until='networkidle')
            await pg.evaluate(TRAV_LOGIN, '9' + str(random.randint(100000000, 999999999)))
            await pg.goto(BASE + '/traveler/app.html', wait_until='networkidle')
            await pg.wait_for_timeout(1000)
            rate = await pg.evaluate("() => { const c = document.querySelector('.cat-chip[data-cat=general]'); return c && c.dataset.rate; }")
            check('مسافر: نرخ general از سرور خوانده شد (1777000)', rate == '1777000')
            med = await pg.evaluate("() => { const c = document.querySelector('.cat-chip[data-cat=medical]'); return c && c.dataset.rate; }")
            check('مسافر: نرخ medical همچنان از تعرفه (1685000)', med == '1685000')
            check('مسافر: بدون خطای JS', not errs)
            await pg.close()
            # ---- مترجم: کارت‌های جفت‌زبان
            tp = await b.new_page(viewport={'width': 390, 'height': 844})
            terr = []
            tp.on('pageerror', lambda e: terr.append(str(e)))
            await tp.goto(BASE + '/translator/index.html', wait_until='networkidle')
            await tp.wait_for_timeout(800)
            n = await tp.evaluate("() => document.querySelectorAll('#langCards .lang-item').length")
            check('مترجم: ۶ جفت‌زبان فعال در #langCards', n == 6)
            labels = await tp.evaluate("() => [...document.querySelectorAll('#langCards h4')].map(h => h.textContent)")
            check('مترجم: برچسب ترکی از کاتالوگ آمده', any('ترکی' in x for x in labels))
            check('مترجم: بدون خطای JS', not terr)
            await tp.close()
            await b.close()
    finally:
        st, _ = api('PUT', '/admin/settings', {'hourly_tariffs': old_tariff if isinstance(old_tariff, dict) else json.loads(old_tariff)}, token=tok)
        check('بازگردانی تعرفه', st == 200)
    ok = all(results)
    print('RESULT %d/%d' % (sum(results), len(results)))
    sys.exit(0 if ok else 1)

asyncio.run(main())
