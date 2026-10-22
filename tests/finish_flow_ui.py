# روی صفحه‌ی تایمر مسافر باید بنر «درخواست پایان مترجم» با قبول/رد و دکمه‌ی پایان خود مسافر باشد.
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
        info = await pg.evaluate("""()=>{
          var s5 = document.getElementById('stage-5');
          var banner = document.getElementById('finish-request-banner');
          return {
            bannerInStage5: !!(banner && s5 && s5.contains(banner)),
            approve: !!document.getElementById('btn-approve-finish'),
            reject: !!document.getElementById('btn-reject-finish'),
            ownFinish: !!document.getElementById('btn-finish-service'),
            bannerText: banner ? banner.innerText : ''
          };
        }""")
        print(info)
        print('finish request banner on timer page:', info['bannerInStage5'] and info['approve'] and info['reject'])
        print('traveler own finish button exists:', info['ownFinish'])
        print('banner explains full amount:', 'مبلغ کامل' in info['bannerText'])
        print('errors:', [e for e in errs if 'tailwind' not in e] or 'none')
        await b.close()

asyncio.run(m())
