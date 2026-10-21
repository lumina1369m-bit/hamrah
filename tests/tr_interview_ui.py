# تست کارت مصاحبه‌ی زنده در میز کار مترجم: نمایش نوبت‌های آزاد، رزرو، و نبودن اتاق ویدئویی (هماهنگی حضوری یا بیرونی)
import asyncio, re, json, random, datetime, sys, urllib.request
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
PASSWORD = 'test-admin-pass'
PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

def api(method, path, body=None, token=None):
    h = {'Content-Type': 'application/json'}
    if token: h['Authorization'] = 'Bearer ' + token
    rq = urllib.request.Request(BASE + '/api' + path, method=method, headers=h,
                                data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(rq, timeout=10) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')

# ورود و ثبت‌نام مترجم از راه API (بدون تأیید؛ مصاحبه قبل از تأیید انجام می‌شود)
PHONE_JS = """async ([phone, token]) => {
  const st = HZ.load(); st.token = token; st.session = {phone, until: Date.now() + 3600e3};
  for (let i = 0; i < 8; i++) st.completed[i] = true; st.status = 'active_general'; st.profile = {nameFa: 'نازنین', lastFa: 'تست'}; HZ.save(st); return true;
}"""

async def main():
    phone = '9' + str(random.randint(100000000, 999999999))
    api('POST', '/auth/request-code', {'phone': phone, 'role': 'translator'})
    _, v = api('POST', '/auth/verify', {'phone': phone, 'role': 'translator', 'code': '123456'})
    tok = v['token']
    api('POST', '/translator/registration', {'nda': True, 'charter': True, 'gender': 'female', 'first_name': 'نازنین',
        'last_name': 'تست', 'city': 'تهران', 'car': False, 'languages': ['ar', 'fa'], 'fields': ['general']}, tok)
    _, adm = api('POST', '/admin/login', {'password': PASSWORD})
    atok = adm.get('token')
    soon = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)
    _, sl = api('POST', '/admin/interview-slots', {'starts_at': soon.isoformat()}, atok)
    _, sl2 = api('POST', '/admin/interview-slots', {'starts_at': (soon + datetime.timedelta(hours=1)).isoformat()}, atok)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 1280, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto(BASE + '/translator/index.html'); await pg.wait_for_timeout(600)
        await pg.evaluate(PHONE_JS, [phone, tok])
        await pg.goto(BASE + '/translator/app.html'); await pg.wait_for_timeout(1500)
        await pg.evaluate("""()=>{ const b=[...document.querySelectorAll('button')].find(x=>x.getAttribute('onclick')==="switchView('credentials')"); b.click(); }"""); await pg.wait_for_timeout(1200)
        box = await pg.evaluate("()=>{const e=document.getElementById('iv-box'); return e ? e.innerText : null}")
        check('کارت مصاحبه در میز کار نمایش داده می‌شود', box is not None and 'مصاحبه' in box)
        btns = pg.locator('#iv-box button')
        n = await btns.count()
        check('نوبت‌های آزاد به‌صورت دکمه نمایش داده می‌شوند', n >= 2)
        await pg.evaluate("()=>{const bs=[...document.querySelectorAll('#iv-box button')]; bs[0].click();}")
        await pg.wait_for_timeout(1200)
        box2 = await pg.evaluate("()=>document.getElementById('iv-box').innerText")
        check('پس از رزرو، نوبت شما نمایش داده می‌شود', 'نوبت شما' in box2)
        msg = await pg.evaluate("()=>document.getElementById('iv-box').innerText")
        check('دکمه‌ی ورود به اتاق مصاحبه وجود ندارد', await pg.get_by_role('button', name='ورود به اتاق مصاحبه').count() == 0)
        check('لینک اتاق در میز کار نیست', 'rooms.hamzaban' not in msg)
        check('خطای صفحه', not errs)
        await b.close()
    print('RESULT:', 'PASS' if all(results) else 'FAIL', f'({sum(results)}/{len(results)})')
    sys.exit(0 if all(results) else 1)

asyncio.run(main())
