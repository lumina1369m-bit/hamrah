# تست پنل مدیریت برای نوبت‌های مصاحبه: افزودن نوبت، نمایش رزرو، ثبت عدم حضور
import asyncio, sys, json, random, urllib.request, datetime
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

def fa(x):
    return str(x).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

def make_translator():
    phone = '9' + str(random.randint(100000000, 999999999))
    api('POST', '/auth/request-code', {'phone': phone, 'role': 'translator'})
    _, v = api('POST', '/auth/verify', {'phone': phone, 'role': 'translator', 'code': '123456'})
    tok = v['token']
    api('POST', '/translator/registration', {'nda': True, 'charter': True, 'gender': 'male', 'first_name': 'سامان',
        'last_name': 'تست', 'city': 'شیراز', 'car': False, 'languages': ['en', 'fa'], 'fields': ['general']}, tok)
    return phone, tok

async def main():
    phone, tok = make_translator()
    shown = fa(phone)
    _, adm = api('POST', '/admin/login', {'password': PASSWORD})
    atok = adm.get('token')
    future = datetime.datetime.utcnow() + datetime.timedelta(days=2)
    st, sl = api('POST', '/admin/interview-slots', {'starts_at': future.isoformat() + 'Z'}, atok)
    check('نوبت از سمت مدیر ساخته شد', st == 201)
    st, _ = api('POST', '/translator/interview-slots/%d/book' % sl['id'], None, tok)
    check('مترجم نوبت آزاد را رزرو کرد', st == 200)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 1024, 'height': 800})
        page = await ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:120]))
        page.on('dialog', lambda d: asyncio.ensure_future(d.dismiss()))
        await page.goto(BASE + '/admin/index.html'); await page.wait_for_timeout(500)
        await page.fill('#pw', PASSWORD); await page.click('#login-btn'); await page.wait_for_timeout(900)
        await page.click('.tabs button[data-tab=review]'); await page.wait_for_timeout(700)
        row = page.locator('#slot-body tr', has_text=shown)
        check('نوبت رزروشده با شماره‌ی مترجم نمایش داده می‌شود', await row.count() == 1)
        check('وضعیت «رزرو شده» است', await row.count() == 1 and 'رزرو شده' in (await row.first.text_content() or ''))
        # افزودن نوبت از فرم
        dt = (datetime.datetime.now() + datetime.timedelta(days=3)).strftime('%Y-%m-%dT10:30')
        await page.fill('#slot-at', dt); await page.click('#slot-add'); await page.wait_for_timeout(700)
        msg = await page.text_content('#slot-msg')
        check('افزودن نوبت پیام موفقیت می‌دهد', 'ثبت شد' in (msg or ''))
        check('نوبت تازه در فهرست است', await page.locator('#slot-body tr', has_text='آزاد').count() >= 1)
        # عدم حضور
        await row.locator('.ns-btn').click(); await page.wait_for_timeout(700)
        row2 = page.locator('#slot-body tr', has_text=shown)
        check('پس از عدم حضور، وضعیت «عدم حضور» است', await row2.count() == 1 and 'عدم حضور' in (await row2.first.text_content() or ''))
        check('پیام عدم حضور نمایش داده می‌شود', 'آزاد شد' in (await page.text_content('#slot-msg') or ''))
        check('خطای صفحه', not errs)
        await b.close()
    print('RESULT: %s (%d/%d)' % ('PASS' if all(results) else 'FAIL', sum(results), len(results)))
    sys.exit(0 if all(results) else 1)

asyncio.run(main())
