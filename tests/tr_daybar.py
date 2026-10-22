import asyncio, re, json, datetime
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS, SEED_JS
def iso(days, h=10):
    d = datetime.datetime.now().replace(hour=h, minute=0, second=0, microsecond=0) + datetime.timedelta(days=days)
    return d.strftime('%Y-%m-%dT%H:%M:00')
M = [
  {'code':'M-1','purpose':'امروز','travelerName':'A','place':'x','startAt':iso(0,15),'total':100,'net':80,'status':'accepted'},
  {'code':'M-2','purpose':'دو روز بعد','travelerName':'B','place':'y','startAt':iso(2,9),'total':200,'net':160,'status':'accepted'},
  {'code':'M-3','purpose':'دو روز بعد عصر','travelerName':'C','place':'z','startAt':iso(2,18),'total':300,'net':240,'status':'accepted'},
  {'code':'M-4','purpose':'در انتظار','travelerName':'D','place':'w','startAt':iso(1,9),'total':50,'net':40,'status':'pending_invite'},
]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto('http://127.0.0.1:8081/translator/index.html'); await pg.wait_for_timeout(600)
        import random
        token = await pg.evaluate(LOGIN_JS, '9' + str(random.randint(100000000, 999999999)))
        await pg.evaluate(SEED_JS, [token, M])
        await pg.goto('http://127.0.0.1:8081/translator/app.html'); await pg.wait_for_timeout(1400)
        bar = await pg.evaluate("()=>[...document.querySelectorAll('#day-bar button')].map(b=>b.textContent.replace(/\\s+/g,' ').trim())")
        print('bar:', json.dumps(bar, ensure_ascii=False))
        for idx in (0, 2, 1, 3):
            await pg.evaluate("i=>document.querySelectorAll('#day-bar button')[i].click()", idx)
            await pg.wait_for_timeout(200)
            cards = await pg.evaluate("()=>[...document.getElementById('schedule-list').children].map(c=>c.textContent.slice(0,20))")
            print(f'day {idx}:', json.dumps(cards, ensure_ascii=False))
        print('pressed:', await pg.evaluate("()=>[...document.querySelectorAll('#day-bar button')].map(b=>b.getAttribute('aria-pressed'))"))
        print('errors:', errs or 'none')
        await b.close()
asyncio.run(main())
