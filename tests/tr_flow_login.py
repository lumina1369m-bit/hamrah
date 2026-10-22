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
        await pg.fill('#mobileInput', '9123456703'); await pg.check('#c-age'); await pg.check('#c-terms'); await pg.wait_for_timeout(300)
        print('send disabled after phone:', await pg.is_disabled('#sendOtpBtn'))
        await pg.click('#sendOtpBtn', timeout=3000); await pg.wait_for_timeout(800)
        st = await pg.evaluate("""()=>['step-panel-1','step-panel-2','step-panel-3'].map(i=>{const e=document.getElementById(i);return i+':'+(e&&e.offsetHeight?'shown':'hidden')})""")
        print('after send:', st)
        info = await pg.evaluate("""()=>[...document.querySelectorAll('#step-panel-2 input, #step-panel-1 input')].map(e=>(e.id||e.name||e.type)+'|'+(e.offsetHeight?'vis':'hid')+'|'+e.value)""")
        print('inputs:', info)
        await pg.screenshot(path=f'assets/tr_after_send_{W}.png', full_page=False)
        print('errors:', errs[:5] or 'none')
        inputs2 = await pg.evaluate("""()=>[...document.querySelectorAll('input')].filter(e=>e.offsetHeight).map(e=>(e.id||e.name||e.type)+'|'+e.maxLength+'|'+e.value)""")
        print('visible inputs now:', inputs2)
        print('send text:', await pg.text_content('#sendOtpBtn'))
        await b.close()
asyncio.run(main())
