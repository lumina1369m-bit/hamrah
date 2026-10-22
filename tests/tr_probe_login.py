import asyncio, re, json
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        for w in (390, 1280):
            ctx = await b.new_context(viewport={'width': w, 'height': 844})
            await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.googleapis\.com|fonts\.gstatic\.com).*'), lambda r: r.abort())
            pg = await ctx.new_page(); errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
            pg.on('console', lambda m: errs.append('console:' + m.text[:120]) if m.type == 'error' else None)
            await pg.goto('http://127.0.0.1:8081/translator/index.html'); await pg.wait_for_timeout(1500)
            print('== width', w, 'url', pg.url.split('/')[-1])
            info = await pg.evaluate("""()=>{
              const vis = e => !!(e.offsetWidth || e.offsetHeight) && getComputedStyle(e).visibility !== 'hidden';
              const btns=[...document.querySelectorAll('button,a')].filter(vis).map(e=>(e.id||'')+'|'+(e.textContent||'').trim().slice(0,30)+'|dis='+e.disabled);
              const inputs=[...document.querySelectorAll('input,select,textarea')].filter(vis).map(e=>(e.id||e.name||e.type)+'|'+(e.placeholder||'')+'|val='+e.value.slice(0,15));
              const steps=[...document.querySelectorAll('[id^=step],[id^=screen],[data-step]')].map(e=>e.id+':'+(vis(e)?'shown':'hidden'));
              return {btns, inputs, steps, bodyH: document.body.scrollHeight};
            }""")
            print(json.dumps(info, ensure_ascii=False, indent=1)[:2500])
            await pg.screenshot(path=f'assets/tr_login_{w}.png', full_page=True)
            print('errors:', errs[:8] or 'none')
            await ctx.close()
        await b.close()
asyncio.run(main())
