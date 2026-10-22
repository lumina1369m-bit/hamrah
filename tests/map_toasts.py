import asyncio, re, json, sys
from playwright.async_api import async_playwright
lang = sys.argv[1]
PF = re.compile(r'[پچژگک]')
ANY = re.compile(r'[\u0600-\u06FF]')
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        await ctx.route(re.compile(r'https://(unpkg\.com|fonts\.googleapis\.com|fonts\.gstatic\.com|nominatim\.openstreetmap\.org|tile\.openstreetmap\.org).*'), lambda r: r.abort())
        await ctx.add_init_script("if(!sessionStorage.getItem('s')){localStorage.setItem('hamzaban.user.v1',JSON.stringify({name:'T'}));localStorage.setItem('hamzaban_lang','%s');sessionStorage.setItem('s','1')}" % lang)
        pg = await ctx.new_page(); errs=[]
        pg.on('pageerror', lambda e: errs.append(str(e)[:120]))
        await pg.goto('http://127.0.0.1:8081/traveler/app.html'); await pg.wait_for_timeout(1500)
        results = []
        async def act(name, fn):
            await pg.evaluate("()=>{const t=document.getElementById('toast-pill');if(t)t.classList.add('hidden');}")
            try:
                await fn()
            except Exception as e:
                results.append((name, 'ACTION FAILED: ' + str(e)[:80])); return
            await pg.wait_for_timeout(700)
            msg = await pg.evaluate("()=>{const p=document.getElementById('toast-pill');return p&&!p.classList.contains('hidden')?document.getElementById('toast-text').textContent:null}")
            results.append((name, msg))
        await act('zoom in', lambda: pg.click('button[onclick="mapZoom(1)"]'))
        await act('locate me', lambda: pg.click('button[onclick="locateMe()"]'))
        await act('layers', lambda: pg.locator('button:has-text("layers")').first.click(timeout=2000))
        await act('notifications', lambda: pg.locator('button:has-text("notifications")').first.click(timeout=2000))
        await act('support chat', lambda: pg.locator('button:has-text("chat")').first.click(timeout=2000))
        await act('swap languages', lambda: pg.click('#btn-swap-langs'))
        await act('confirm location (pending)', lambda: pg.click('#confirm-location-btn'))
        await act('confirm location', lambda: pg.click('#confirm-location-btn'))
        await act('change location', lambda: pg.click('#change-location-btn'))
        await pg.wait_for_timeout(500)
        out = []
        for name, msg in results:
            flag = ''
            if msg:
                if lang == 'en' and ANY.search(msg): flag = '  <-- PERSIAN'
                if lang == 'ar' and PF.search(msg): flag = '  <-- PERSIAN'
            out.append('%-28s %s%s' % (name, msg, flag))
        print('\n'.join(out))
        print('errors:', errs or 'none')
        await b.close()
asyncio.run(main())
