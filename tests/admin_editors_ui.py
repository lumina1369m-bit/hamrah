# تست ویرایشگرهای ساختاری پنل مدیر: تعرفه‌ها و جفت‌زبان‌ها (ذخیره، رد مقدار نامعتبر، بازگردانی)
import asyncio, sys, json, urllib.request
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
PASSWORD = 'test-admin-pass'
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

async def main():
    _, adm = api('POST', '/admin/login', {'password': PASSWORD})
    atok = adm['token']
    _, before = api('GET', '/admin/settings', None, atok)
    orig_t = before['settings']['hourly_tariffs']['value']
    orig_p = before['settings']['language_pairs']['value']
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 1024, 'height': 900})
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        pg.on('dialog', lambda d: asyncio.ensure_future(d.dismiss()))
        await pg.goto(BASE + '/admin/index.html'); await pg.wait_for_timeout(500)
        await pg.fill('#pw', PASSWORD); await pg.click('#login-btn'); await pg.wait_for_timeout(900)
        await pg.click('.tabs button[data-tab=settings]'); await pg.wait_for_timeout(700)
        check('ویرایشگر تعرفه چهار ردیف دارد', await pg.locator('input[data-tkey]').count() == 4)
        check('ویرایشگر جفت‌زبان ردیف‌های فعلی را دارد', await pg.locator('.prow').count() >= 1)
        # تعرفه‌ی پزشکی را تغییر بده و ذخیره کن
        await pg.fill('input[data-tkey=medical]', '1700000')
        await pg.click('#save-settings'); await pg.wait_for_timeout(800)
        msg = await pg.text_content('#msg')
        check('ذخیره‌ی تعرفه پیام موفقیت می‌دهد', 'ذخیره شد' in (msg or ''))
        _, now_s = api('GET', '/admin/settings', None, atok)
        check('تعرفه‌ی جدید روی سرور ثبت شد', json.loads(now_s['settings']['hourly_tariffs']['value'])['medical'] == 1700000)
        # جفت‌زبان نامعتبر: کد خراب باید رد شود
        await pg.evaluate("()=>{const i=document.querySelector('.prow .pc'); i.value='bad';}")
        await pg.click('#save-settings'); await pg.wait_for_timeout(800)
        msg2 = await pg.text_content('#msg')
        check('کد نامعتبر جفت‌زبان رد می‌شود و پیام مشخص می‌دهد', 'مقدار نامعتبر' in (msg2 or '') and 'جفت‌زبان' in (msg2 or ''))
        check('خطای صفحه', not errs)
        await b.close()
    # بازگردانی مقدارهای اصلی
    api('PUT', '/admin/settings', {'hourly_tariffs': json.loads(orig_t), 'language_pairs': json.loads(orig_p)}, atok)
    print('RESULT:', 'PASS' if all(results) else 'FAIL', f'({sum(results)}/{len(results)})')
    sys.exit(0 if all(results) else 1)

asyncio.run(main())
