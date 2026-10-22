# کارت تمدید باید همیشه روی صفحه‌ی تایمر (مرحله‌ی ۵) باشد، نه فقط در نیم ساعت پایانی.
# دکمه‌ی تمدید داخل کارت تمدید است و هشدار نیم ساعت آخر دکمه ندارد.
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
          var card = document.getElementById('extension-card');
          var btn = document.getElementById('btn-extend-one-hour');
          var warn = document.getElementById('expiry-warning');
          var stage5 = document.getElementById('stage-5');
          return {
            cardInStage5: !!(card && stage5 && stage5.contains(card)),
            btnInCard: !!(btn && card && card.contains(btn)),
            btnText: btn ? btn.innerText : '',
            warnHasButton: warn ? !!warn.querySelector('button') : null,
            cardHidden: card ? card.classList.contains('hidden') : null,
            statusEl: !!document.getElementById('extension-status')
          };
        }""")
        print(info)
        print('extension card always on timer page:', info['cardInStage5'] and info['btnInCard'] and not info['cardHidden'])
        print('extend button label ok:', 'تمدید خدمت' in info['btnText'])
        print('warning has no button:', info['warnHasButton'] is False)
        print('status element exists:', info['statusEl'])
        print('errors:', [e for e in errs if 'tailwind' not in e] or 'none')
        await b.close()

asyncio.run(m())
