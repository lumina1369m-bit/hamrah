# تست ماموریت‌های من و برنامه‌ی کاری در میز کار مترجم (سند ۸ و ۹):
# فقط ماموریت‌های پذیرفته‌شده و آینده؛ عنوان فارسی؛ مبلغ کل و سهم خالص؛ نوار ۷ روزه؛ بدون فهرست انتخاب رزرو
import asyncio, re, json, random, datetime, sys
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS, SEED_JS

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

def iso(days, h=10):
    d = datetime.datetime.now().replace(hour=h, minute=0, second=0, microsecond=0) + datetime.timedelta(days=days)
    return d.strftime('%Y-%m-%dT%H:%M:00')

M = [
  {'code': 'M-1', 'purpose': 'general', 'travelerName': 'Christopher', 'place': 'نمایشگاه', 'startAt': iso(5, 9), 'total': 3200000, 'net': 2560000, 'status': 'accepted'},
  {'code': 'M-2', 'purpose': 'مذاکره', 'travelerName': 'Ali', 'place': 'بیمارستان', 'startAt': iso(2, 15), 'total': 900000, 'net': 720000, 'status': 'accepted'},
  {'code': 'M-3', 'purpose': 'medical', 'travelerName': 'Pending', 'place': 'x', 'startAt': iso(6, 9), 'total': 100, 'net': 80, 'status': 'pending_invite'},
  {'code': 'M-4', 'purpose': 'general', 'travelerName': 'Old', 'place': 'y', 'startAt': iso(-10, 9), 'total': 100, 'net': 80, 'status': 'accepted'},
]

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto(BASE + '/translator/index.html'); await pg.wait_for_timeout(600)
        token = await pg.evaluate(LOGIN_JS, '9' + str(random.randint(100000000, 999999999)))
        check('ورود مترجم از طریق API', bool(token))
        await pg.evaluate(SEED_JS, [token, M])
        await pg.goto(BASE + '/translator/app.html'); await pg.wait_for_timeout(1500)
        cards = await pg.evaluate("()=>[...document.getElementById('missions-list').children].map(c=>c.textContent.replace(/\\s+/g,' ').trim())")
        check('فقط دو ماموریت پذیرفته‌شده‌ی آینده نشان داده می‌شود', len(cards) == 2)
        check('ماموریت در انتظار و گذشته نشان داده نمی‌شود', not any('Old' in c or 'Pending' in c for c in cards))
        check('عنوان زمینه فارسی است (نه کد general)', any('عمومی' in c for c in cards) and not any('general' in c for c in cards))
        check('مبلغ کل و سهم خالص نمایش داده می‌شود', all('مبلغ کل' in c and 'سهم شما' in c for c in cards))
        check('کارت فهرست انتخاب رزرو ندارد', await pg.locator('text=انتخاب رزرو').count() == 0)
        bar = await pg.evaluate("()=>[...document.querySelectorAll('#day-bar button')].length")
        check('نوار روز هفت روز دارد', bar == 7)
        # برنامه: روز ۲ (دو روز بعد) یک ماموریت دارد، روز ۱ استراحت است
        await pg.evaluate("()=>document.querySelectorAll('#day-bar button')[2].click()")
        await pg.wait_for_timeout(300)
        day2 = await pg.evaluate("()=>[...document.getElementById('schedule-list').children].map(c=>c.textContent)")
        check('روز انتخابی فقط ماموریت همان روز را دارد', len(day2) == 1 and 'مذاکره' in day2[0])
        await pg.evaluate("()=>document.querySelectorAll('#day-bar button')[1].click()")
        await pg.wait_for_timeout(300)
        day1 = await pg.evaluate("()=>[...document.getElementById('schedule-list').children].map(c=>c.textContent)")
        check('روز بدون ماموریت پیام خالی می‌دهد', len(day1) == 1 and 'ماموریتی ندارید' in day1[0])
        check('خطای صفحه', not errs)
        await b.close()
    print('RESULT:', 'PASS' if all(results) else 'FAIL', f'({sum(results)}/{len(results)})')
    sys.exit(0 if all(results) else 1)

asyncio.run(main())
