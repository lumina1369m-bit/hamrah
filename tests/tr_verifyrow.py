import asyncio, re
from playwright.async_api import async_playwright
async def m():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox']); pg = await b.new_page(viewport={'width':390,'height':844})
        await pg.goto('http://127.0.0.1:8081/translator/index.html'); await pg.wait_for_timeout(1000)
        print('before send hidden:', await pg.evaluate("()=>document.getElementById('verifyRow').classList.contains('hidden')"))
        await pg.check('#c-age'); await pg.check('#c-terms'); await pg.fill('#mobileInput','9123456704')
        await pg.click('#sendOtpBtn'); await pg.wait_for_timeout(400)
        print('after send visible:', await pg.evaluate("()=>!document.getElementById('verifyRow').classList.contains('hidden')"))
        boxes = pg.locator('#step-panel-1 input[type=text]')
        for i,d in enumerate('123456'): await boxes.nth(i).fill(d)
        await pg.wait_for_timeout(900)
        print('step2 reached:', await pg.evaluate("()=>document.getElementById('step-panel-2').offsetHeight>0"))
        await b.close()
asyncio.run(m())
