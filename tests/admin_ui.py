# تست پنل مدیریت در مرورگر: ورود نادرست و درست، خلاصه، ذخیره‌ی تنظیمات و اعمال آن.
import asyncio, sys
from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:8081'
PASSWORD = 'test-admin-pass'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 1024, 'height': 800})
        page = await ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:120]))
        await page.goto(BASE + '/admin/index.html'); await page.wait_for_timeout(500)
        await page.fill('#pw', 'wrong')
        await page.click('#login-btn'); await page.wait_for_timeout(600)
        msg = await page.text_content('#login-msg')
        check('رمز نادرست پیام خطا می‌دهد', 'نادرست' in (msg or ''))
        await page.fill('#pw', PASSWORD)
        await page.click('#login-btn'); await page.wait_for_timeout(900)
        check('ورود درست، پنل را باز می‌کند', await page.is_visible('#app-view'))
        check('خلاصه وضعیت را نشان می‌دهد', await page.locator('#stats .stat').count() > 0)
        await page.click('.tabs button[data-tab=settings]'); await page.wait_for_timeout(700)
        check('فرم تنظیمات بارگذاری شد', await page.is_visible('#set-hourly_tariffs'))
        check('مهلت‌های ثابت در فرم نیستند', await page.locator('#set-offer_ms').count() == 0)
        await page.fill('#set-cancel_fee_percent', '25')
        await page.click('#save-settings'); await page.wait_for_timeout(700)
        check('ذخیره‌ی تنظیمات پیام موفق دارد', 'ذخیره شد' in (await page.text_content('#msg') or ''))
        await page.reload(); await page.wait_for_timeout(800)
        await page.click('.tabs button[data-tab=settings]'); await page.wait_for_timeout(700)
        check('مقدار ذخیره‌شده بعد از بارگذاری مجدد می‌ماند', await page.input_value('#set-cancel_fee_percent') == '25')
        await page.fill('#set-cancel_fee_percent', '20')
        await page.click('#save-settings'); await page.wait_for_timeout(600)
        await page.click('#logout'); await page.wait_for_timeout(500)
        check('خروج، فرم ورود را برمی‌گرداند', await page.is_visible('#login-view'))
        check('خطای صفحه‌ها', not errs)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})', errs if errs else '')
        sys.exit(0 if ok else 1)

asyncio.run(main())
