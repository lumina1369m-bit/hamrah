# تست پنل مدیریت برای مدارک و مصاحبه: فهرست مدارک، نمایش، رد با دلیل، تأیید؛ و دکمه‌های مصاحبه‌ی زبان
import asyncio, sys, json, random, urllib.request
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

def make_translator():
    phone = '9' + str(random.randint(100000000, 999999999))
    api('POST', '/auth/request-code', {'phone': phone, 'role': 'translator'})
    _, v = api('POST', '/auth/verify', {'phone': phone, 'role': 'translator', 'code': '123456'})
    tok = v['token']
    api('POST', '/translator/registration', {'nda': True, 'charter': True, 'gender': 'female', 'first_name': 'نگار',
        'last_name': 'تست', 'city': 'تهران', 'car': False, 'languages': ['ar', 'fa'], 'fields': ['general']}, tok)
    st, d = api('POST', '/translator/documents', {'kind': 'nid_card', 'data': PNG}, tok)
    return phone, tok, st

def fa(x):
    return str(x).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

async def main():
    phone, tok, st_up = make_translator()
    shown = fa(phone)  # پنل شماره را با ارقام فارسی نشان می‌دهد
    check('مترجم آزمایشی با کارت ملی ثبت شد', st_up == 200)
    _, adm = api('POST', '/admin/login', {'password': PASSWORD})
    atok = adm.get('token')
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 1024, 'height': 800})
        page = await ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:120]))
        page.on('dialog', lambda d: asyncio.ensure_future(d.dismiss()))
        await page.goto(BASE + '/admin/index.html'); await page.wait_for_timeout(500)
        await page.fill('#pw', PASSWORD); await page.click('#login-btn'); await page.wait_for_timeout(900)
        # بررسی مترجمان: دکمه‌های مصاحبه
        await page.click('.tabs button[data-tab=review]'); await page.wait_for_timeout(700)
        row_ok = await page.locator('#review-body tr', has_text=shown).count() == 1
        check('مترجم در فهرست بررسی است', row_ok)
        await page.locator('#review-body tr', has_text=shown).locator('.int-pass').click()
        await page.wait_for_timeout(600)
        msg = await page.text_content('#msg')
        check('ثبت «مصاحبه: قبول» پیام موفقیت می‌دهد', 'قبول' in (msg or ''))
        # تب مدارک
        await page.click('.tabs button[data-tab=docs]'); await page.wait_for_timeout(700)
        row = page.locator('#docs-body tr', has_text=shown)
        check('مدرک در فهرست مدارک است', await row.count() == 1)
        # نمایش: یک تب جدید (blob) باز می‌شود
        async with ctx.expect_page() as popup_info:
            await row.locator('.view-btn').click()
        popup = await popup_info.value
        check('نمایش مدرک فایل را در تب جدید باز می‌کند', popup.url.startswith('blob:'))
        await popup.close()
        # رد بدون دلیل پذیرفته نیست (پنجره‌ی دلیل خالی)
        await row.locator('.rej-btn').click(); await page.wait_for_timeout(500)
        msg = await page.text_content('#msg')
        check('رد بدون دلیل انجام نمی‌شود', 'بدون دلیل' in (msg or ''))
        still = api('GET', '/admin/documents?status=uploaded', None, atok)
        check('مدرک پس از رد بی‌دلیل هنوز در انتظار است', any(d['phone'] == phone for d in still[1].get('documents', [])))
        # تأیید
        await page.locator('#docs-body tr', has_text=shown).locator('.ok-btn').click(); await page.wait_for_timeout(700)
        msg = await page.text_content('#msg')
        check('تأیید مدرک پیام موفقیت می‌دهد', 'تأیید شد' in (msg or ''))
        _, st = api('GET', '/translator/documents', None, tok)
        check('وضعیت مدرک برای مترجم «تأیید شده» است', any(d['kind'] == 'nid_card' and d['status'] == 'approved' for d in st.get('documents', [])))
        check('خطای صفحه', not errs)
        await b.close()
    ok = all(results)
    print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})')
    sys.exit(0 if ok else 1)

asyncio.run(main())
