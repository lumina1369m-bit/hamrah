# در اپ مسافر نباید هیچ دکمه‌ی شبیه‌سازی باشد؛ صفحه‌ی تطبیق فقط با وضعیت واقعی سرور جلو می‌رود.
import asyncio
from playwright.async_api import async_playwright

async def m():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto('http://127.0.0.1:8081/traveler/index.html'); await pg.wait_for_timeout(400)
        await pg.evaluate("()=>{localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'Ali',last:'Rezaei',gender:'male',contact:'+98 912 345 6789',lang:'fa',passport:null}));localStorage.setItem('hamzaban_lang','fa')}")
        await pg.goto('http://127.0.0.1:8081/traveler/app.html'); await pg.wait_for_timeout(1500)
        ids = await pg.evaluate("""()=>({
          simFound: !!document.getElementById('btn-sim-found'),
          simArrived: !!document.getElementById('btn-sim-arrived'),
          arrived: !!document.getElementById('btn-arrived'),
          simText: document.body.innerText.includes('شبیه‌سازی')
        })""")
        print(ids)
        print('no sim buttons:', not ids['simFound'] and not ids['simArrived'] and not ids['simText'])
        print('real arrived button exists:', ids['arrived'])
        await pg.click('#btn-main-submit'); await pg.wait_for_timeout(800)
        stage2 = await pg.evaluate("()=>!document.getElementById('stage-2').classList.contains('hidden')")
        print('matching page shown:', stage2)
        print('errors:', [e for e in errs if 'tailwind' not in e] or 'none')
        await b.close()

asyncio.run(m())
