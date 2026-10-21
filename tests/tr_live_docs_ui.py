# تست وضعیت زنده‌ی مدارک در میز کار مترجم: مدرک ارسالی و وضعیت آن نشان داده می‌شود
import asyncio, re, sys, random
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        P = await ctx.new_page(); perr = []
        P.on('pageerror', lambda e: perr.append(str(e)[:120]))
        await P.goto(BASE + '/translator/index.html'); await P.wait_for_timeout(600)
        phone = '9' + str(random.randint(100000000, 999999999))
        await P.evaluate(LOGIN_JS, phone)
        tok = await P.evaluate("()=>HZ.load().token")
        await P.evaluate("async (t)=>{ await fetch('/api/dev/approve-translator',{method:'POST',headers:{Authorization:'Bearer '+t}}); }", tok)
        status = await P.evaluate("""async ([t, png]) => {
          const x = await fetch('/api/translator/documents', {method:'POST', headers:{'Content-Type':'application/json', Authorization:'Bearer '+t}, body: JSON.stringify({kind:'criminal_record', data: png, expires_at:'2031-01-01'})});
          return x.status; }""", [tok, PNG])
        check('گواهی سوءپیشینه ارسال شد', status == 200)
        await P.goto(BASE + '/translator/app.html'); await P.wait_for_timeout(1500)
        await P.evaluate("()=>{ const b=document.querySelector('[data-target=credentials]') || [...document.querySelectorAll('button')].find(x=>x.getAttribute('onclick')&&x.getAttribute('onclick').includes(\"switchView('credentials')\")); if (b) b.click(); else switchView('credentials'); }")
        await P.wait_for_timeout(800)
        txt = await P.evaluate("()=>document.getElementById('live-docs-box') ? document.getElementById('live-docs-box').textContent : ''")
        check('نام مدرک نشان داده می‌شود', 'گواهی عدم سوءپیشینه' in txt)
        check('وضعیت «در انتظار بررسی» نشان داده می‌شود', 'در انتظار بررسی' in txt)
        check('محتوای مدرک نشان داده نمی‌شود', 'iVBOR' not in txt)
        cap = await P.evaluate("()=>document.getElementById('cap-box') ? document.getElementById('cap-box').textContent : ''")
        check('چهار بُعد صلاحیت از سرور نشان داده می‌شود', 'احراز هویت' in cap and 'صلاحیت پزشکی' in cap)
        static_hidden = await P.evaluate("()=>{const g=document.getElementById('static-cap-grid'); return !g || getComputedStyle(g).display === 'none';}")
        check('متن نمایشی ثابت CAP دیده نمی‌شود', static_hidden)
        check('خطای صفحه', not perr)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})')
        sys.exit(0 if ok else 1)

asyncio.run(main())
