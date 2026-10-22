# تست پنل مدیریت: تب امکانات و شهرها، ذخیره‌ی امکان، افزودن شهر، گزارش تغییرات و جلوگیری از تزریق HTML.
import asyncio, sys
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8097'
PASSWORD = 'test-admin-pass'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 1024, 'height': 900})
        page = await ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:120]))
        await page.goto(BASE + '/admin/index.html'); await page.wait_for_timeout(500)
        await page.fill('#pw', PASSWORD)
        await page.click('#login-btn'); await page.wait_for_timeout(900)
        await page.click('.tabs button[data-tab=system]'); await page.wait_for_timeout(900)
        n = await page.locator('[data-feat]').count()
        check('فهرست امکانات بارگذاری شد', n >= 10)
        await page.locator('[data-feat=car_mode]').first.click()
        await page.click('#save-features'); await page.wait_for_timeout(800)
        check('ذخیره‌ی امکان پیام موفق دارد', 'ذخیره شد' in (await page.text_content('#features-msg') or ''))
        await page.reload(); await page.wait_for_timeout(700)
        await page.click('.tabs button[data-tab=system]'); await page.wait_for_timeout(800)
        check('وضعیت امکان بعد از بارگذاری مجدد می‌ماند', not await page.locator('[data-feat=car_mode]').first.is_checked())
        await page.fill('#city-new-fa', '<img src=x onerror="window.__xss=1">')
        await page.fill('#city-new-lat', '35.7'); await page.fill('#city-new-lng', '51.4')
        await page.click('#city-add'); await page.wait_for_timeout(800)
        check('شهر جدید اضافه شد', 'اضافه شد' in (await page.text_content('#cities-msg') or ''))
        check('نام شهر به صورت متن نمایش داده می‌شود (بدون تزریق)', await page.locator('#cities-list img').count() == 0)
        check('اسکریپت تزریق‌شده اجرا نشد', await page.evaluate('window.__xss') is None)
        check('گزارش تغییرات ثبت شده', await page.locator('#audit-list tr').count() > 1)
        check('خطای صفحه‌ها', not errs)
        await ctx.close(); await b.close()
    failed = results.count(False)
    print(f'نتیجه: {results.count(True)} موفق، {failed} ناموفق')
    sys.exit(1 if failed else 0)

asyncio.run(main())
