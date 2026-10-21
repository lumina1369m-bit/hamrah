import asyncio, re
from playwright.async_api import async_playwright
async def m():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width':390,'height':844})
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto('http://127.0.0.1:8081/traveler/index.html'); await pg.wait_for_timeout(500)
        await pg.evaluate("()=>{localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'Ali',last:'Rezaei',gender:'male',contact:'+98 912 345 6789',lang:'fa',passport:null}));localStorage.setItem('hamzaban_lang','fa')}")
        await pg.goto('http://127.0.0.1:8081/traveler/app.html'); await pg.wait_for_timeout(2500)
        print('leaflet loaded:', await pg.evaluate("()=>typeof window.L !== 'undefined' && !!window.L.map"))
        print('map container:', await pg.evaluate("()=>{const e=document.querySelector('.leaflet-container');return e? 'yes':'no'}"))
        print('tiles:', await pg.evaluate("()=>document.querySelectorAll('.leaflet-tile').length"))
        print('errors:', errs or 'none')
        await pg.screenshot(path='assets/map_real.png')
        await b.close()
asyncio.run(m())
