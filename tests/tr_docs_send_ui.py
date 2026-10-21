# تست ارسال کامل مدارک در مرورگر: انتخاب فایل در گام‌های ۱، ۲ و ۴ → ثبت پرونده → سرور مدارک را دارد
import asyncio, re, sys, random, os, tempfile
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0f01f0005000201a7e6a9b40000000049454e44ae426082')

async def main():
    tdir = tempfile.mkdtemp()
    png_path = os.path.join(tdir, 'card.png'); open(png_path, 'wb').write(PNG)
    pdf_path = os.path.join(tdir, 'cert.pdf'); open(pdf_path, 'wb').write(b'%PDF-1.4 test')
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
        await pg.goto(BASE + '/translator/index.html'); await pg.wait_for_timeout(700)
        # ۱. ورود
        await pg.fill('#mobileInput', '9' + str(random.randint(100000000, 999999999)))
        await pg.check('#c-age'); await pg.check('#c-terms')
        await pg.click('#sendOtpBtn'); await pg.wait_for_timeout(400)
        boxes = pg.locator('#step-panel-1 input[type=text]')
        for i, d in enumerate('123456'): await boxes.nth(i).fill(d)
        await pg.wait_for_timeout(300)
        # کارت ملی در گام ۱
        await pg.locator("#step-panel-2 input[type=file]").first.set_input_files(png_path)
        # ۲. گام ۲: گواهی سوءپیشینه با تاریخ انقضا؛ سپس به گام‌های بعد برو
        await pg.locator("#step-panel-2 [data-doc-kind='criminal_record'] input[type=file]").set_input_files(pdf_path)
        await pg.locator("#step-panel-2 [data-doc-kind='criminal_record'] input[type=date]").fill('2031-02-01')
        for step in (3, 4):
            await pg.evaluate("""(n)=>{const panel=document.getElementById('step-panel-'+(n-1));
               const btn=[...panel.querySelectorAll('button')].find(b=>(b.getAttribute('onclick')||'').includes('goToStep('+n+')')&&b.offsetHeight);
               if(btn) btn.click();}""", step)
            await pg.wait_for_timeout(300)
        # ۴. گام ۴: گواهینامه با تاریخ انقضا
        await pg.locator("#step-panel-4 [data-doc-kind='licence'] input[type=file]").set_input_files(pdf_path)
        await pg.locator("#step-panel-4 [data-doc-kind='licence'] input[type=date]").fill('2031-01-01')
        await pg.evaluate("""()=>{const panel=document.getElementById('step-panel-4');
               const btn=[...panel.querySelectorAll('button')].find(b=>(b.getAttribute('onclick')||'').includes('goToStep(5)')&&b.offsetHeight);
               if(btn) btn.click();}""")
        await pg.wait_for_timeout(300)
        # ۳. ثبت نهایی
        ok = await pg.evaluate("""()=>{const b=[...document.querySelectorAll('button')].find(b=>(b.getAttribute('onclick')||'').includes('finishRegistration()')&&b.offsetHeight);
           if(!b) return false; b.click(); return true;}""")
        check('دکمه‌ی ثبت نهایی کلیک شد', ok)
        await pg.wait_for_timeout(1500)
        token = await pg.evaluate("()=>HZ.load().token")
        docs = await pg.evaluate("""async (t)=>{const r=await fetch('/api/translator/documents',{headers:{Authorization:'Bearer '+t}});return (await r.json()).documents||[];}""", token)
        kinds = {d['kind']: d for d in docs}
        check('کارت ملی روی سرور است', 'nid_card' in kinds and kinds['nid_card']['status'] == 'uploaded')
        check('گواهی سوءپیشینه با تاریخ انقضا روی سرور است', 'criminal_record' in kinds and bool(kinds['criminal_record'].get('expires_at')))
        check('گواهینامه با تاریخ انقضا روی سرور است', 'licence' in kinds and bool(kinds['licence'].get('expires_at')))
        check('پرونده ثبت شد (در انتظار بررسی نهایی)', await pg.evaluate("()=>HZ.load().status") == 'pending_review')
        check('خطای صفحه', not errs)
        await b.close()
        ok_all = all(results)
        print('RESULT:', 'PASS' if ok_all else 'FAIL', f'({sum(results)}/{len(results)})')
        sys.exit(0 if ok_all else 1)

asyncio.run(main())
