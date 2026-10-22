# تست جستجوی آدرس روی نقشه‌ی اپ مسافر: تایپ مکان ← انتخاب نتیجه ← رفتن پین به همان نقطه و گرفتن نشانی.
# پاسخ‌های Nominatim با route جعلی و قطعی داده می‌شوند تا تست به اینترنت وابسته نباشد.
import asyncio, re, json
from playwright.async_api import async_playwright

SEARCH = [{'lat': '35.6892', 'lon': '51.3890', 'display_name': 'میدان انقلاب، تهران، ایران'}]
REVERSE = {'display_name': 'خیابان انقلاب، تهران، ایران', 'address': {'road': 'خیابان انقلاب', 'city': 'تهران'}}

async def m():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))

        async def geo(route):
            if '/search' in route.request.url:
                body = json.dumps(SEARCH)
            else:
                body = json.dumps(REVERSE)
            await route.fulfill(status=200, content_type='application/json', body=body)
        await pg.route(re.compile(r'nominatim\.openstreetmap\.org'), geo)

        await pg.goto('http://127.0.0.1:8081/traveler/index.html'); await pg.wait_for_timeout(500)
        await pg.evaluate("()=>{localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'Ali',last:'Rezaei',gender:'male',contact:'+98 912 345 6789',lang:'fa',passport:null}));localStorage.setItem('hamzaban_lang','fa')}")
        await pg.goto('http://127.0.0.1:8081/traveler/app.html'); await pg.wait_for_timeout(2500)
        print('search box:', await pg.evaluate("()=>!!document.getElementById('addr-search')"))
        await pg.fill('#addr-search', 'میدان انقلاب')
        await pg.wait_for_selector('#addr-results button', timeout=8000)
        print('results shown:', await pg.evaluate("()=>document.querySelectorAll('#addr-results button').length"))
        await pg.click('#addr-results button')
        await pg.wait_for_timeout(2200)
        mp = await pg.evaluate("()=>window.meetingPoint")
        print('meeting point:', mp)
        ok = bool(mp) and abs(mp['lat'] - 35.6892) < 0.001 and abs(mp['lng'] - 51.3890) < 0.001
        print('pin moved to result:', ok)
        title = await pg.evaluate("()=>document.getElementById('selected-location-title').textContent")
        print('address title:', title)
        print('errors:', [e for e in errs if 'tailwind' not in e] or 'none')
        await b.close()

asyncio.run(m())
