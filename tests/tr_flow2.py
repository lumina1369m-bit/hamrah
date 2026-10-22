import asyncio, re, json, sys
from playwright.async_api import async_playwright
W = int(sys.argv[1]) if len(sys.argv) > 1 else 390
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': W, 'height': 844})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.googleapis\.com|fonts\.gstatic\.com).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
        await pg.goto('http://127.0.0.1:8081/translator/index.html'); await pg.wait_for_timeout(1200)
        await pg.fill('#mobileInput', '9123456702'); await pg.check('#c-age'); await pg.check('#c-terms')
        await pg.click('#sendOtpBtn'); await pg.wait_for_timeout(500)
        boxes = pg.locator('#step-panel-1 input[type=text]')
        n = await boxes.count(); print('boxes', n)
        for i, d in enumerate('123456'):
            await boxes.nth(i).fill(d)
        await pg.wait_for_timeout(1200)
        st = await pg.evaluate("""()=>['step-panel-1','step-panel-2','step-panel-3','step-panel-4','step-panel-5'].map(i=>{const e=document.getElementById(i);return i+':'+(e&&e.offsetHeight?'shown':'hidden')})""")
        print('after code:', st)
        print('active step text:', await pg.evaluate("()=>{const e=[...document.querySelectorAll('[id^=step-panel-]')].find(e=>e.offsetHeight);return e?e.id+' '+e.innerText.slice(0,120).replace(/\\n/g,' / '):'none'}"))
        await pg.screenshot(path=f'assets/tr_step2_{W}.png', full_page=False)
        print('errors:', errs[:5] or 'none')
        await b.close()
asyncio.run(main())
