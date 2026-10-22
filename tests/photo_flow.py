import random
RANDPHONE = '9' + str(random.randint(100000000, 999999999))  # شماره‌ی تازه برای هر اجرا (محدودیت ارسال مجدد)
import asyncio, re, sys
from playwright.async_api import async_playwright
lang = sys.argv[1] if len(sys.argv) > 1 else 'fa'
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        await ctx.route(re.compile(r'https://(unpkg\.com|fonts\.googleapis\.com|fonts\.gstatic\.com).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto('http://127.0.0.1:8081/traveler/index.html'); await pg.wait_for_timeout(600)
        await pg.evaluate("l=>{localStorage.setItem('hamzaban_lang',l); location.reload()}", lang)
        await pg.wait_for_timeout(900)
        await pg.check('#check-age'); await pg.check('#check-terms')
        await pg.fill('#phone-input', RANDPHONE)
        await pg.click('#btn-request-otp', timeout=2000); await pg.wait_for_timeout(600)
        await pg.click('button[onclick="fillTestCode()"]', timeout=2000); await pg.wait_for_timeout(900)
        if await pg.is_visible('#btn-verify'):
            await pg.click('#btn-verify', timeout=2000)
        await pg.wait_for_timeout(900)
        print('identity visible:', await pg.is_visible('#step-identity'))
        open('assets/bad.txt', 'w').write('x')
        await pg.set_input_files('#id-photo', 'assets/bad.txt'); await pg.wait_for_timeout(300)
        print('bad type error:', await pg.evaluate("()=>{const e=document.getElementById('id-photo-err');return [e.classList.contains('hidden'), e.textContent]}"))
        await pg.set_input_files('#id-photo', 'assets/test_photo.png'); await pg.wait_for_timeout(700)
        print('preview img:', await pg.evaluate("()=>!!document.querySelector('#id-photo-preview img')"))
        await pg.fill('#id-name', 'Ali'); await pg.fill('#id-last', 'Rezaei')
        await pg.locator('.id-gender').nth(1).click(); await pg.wait_for_timeout(200)
        await pg.screenshot(path=f'assets/identity_{lang}.png', full_page=True)
        await pg.click('#id-save', timeout=2000); await pg.wait_for_timeout(400)
        print('save label:', await pg.text_content('#id-save'))
        await pg.wait_for_timeout(1800)
        print('url:', pg.url.split('/')[-1])
        has = await pg.evaluate("()=>{const u=JSON.parse(localStorage.getItem('hamzaban.user.v1')||'null');return u&&u.photo?u.photo.slice(0,30):null}")
        print('stored photo:', has)
        await pg.click('nav a[data-nav=account]'); await pg.wait_for_timeout(400)
        print('account avatar img:', await pg.evaluate("()=>!!document.querySelector('#ac-avatar img')"))
        await pg.screenshot(path=f'assets/account_{lang}.png')
        print('errors:', errs or 'none')
        await b.close()
asyncio.run(main())
