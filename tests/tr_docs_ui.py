# تست بخش مدارک گام‌های ۲ و ۴ در اپ مترجم: کادرها ساخته می‌شوند و فایل انتخابی نگه داشته می‌شود
import asyncio, re, sys, os, tempfile
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

async def main():
    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp.write(b'%PDF-1.4 test'); tmp.close()
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        P = await ctx.new_page(); perr = []
        P.on('pageerror', lambda e: perr.append(str(e)[:120]))
        await P.goto(BASE + '/translator/index.html'); await P.wait_for_timeout(800)
        n2 = await P.evaluate("()=>document.querySelectorAll('#step-panel-2 [data-doc-kind]').length")
        n4 = await P.evaluate("()=>document.querySelectorAll('#step-panel-4 [data-doc-kind]').length")
        check('سه کادر مدرک در گام ۲ است', n2 == 3)
        check('پنج کادر مدرک در گام ۴ است', n4 == 5)
        inp = P.locator("#step-panel-2 [data-doc-kind='criminal_record'] input[type=file]")
        await inp.set_input_files(tmp.name)
        await P.wait_for_timeout(300)
        kept = await P.evaluate("()=>!!(window.hzDocFiles && window.hzDocFiles.criminal_record)")
        check('فایل انتخاب‌شده نگه داشته می‌شود', kept)
        label = await P.evaluate("()=>document.querySelector(\"#step-panel-2 [data-doc-kind='criminal_record']\").textContent")
        check('نام فایل نشان داده می‌شود', os.path.basename(tmp.name) in label)
        check('خطای صفحه', not perr)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})')
        os.unlink(tmp.name)
        sys.exit(0 if ok else 1)

asyncio.run(main())
