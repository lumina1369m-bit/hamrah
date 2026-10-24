"""Responsive smoke test: development fixture rows must not render as real missions."""
import asyncio, random, re
from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:8081'
FIXTURES = [
    {'code': 'fixture-1', 'purpose': 'general', 'travelerName': 'Fixture Passenger', 'place': 'Fixture Place',
     'startAt': '2026-11-01T10:00:00.000Z', 'total': 3200000, 'net': 2560000, 'status': 'accepted'},
]
LOGIN_JS = """async (phone) => {
  const headers = {'Content-Type':'application/json'};
  await fetch('/api/auth/request-code',{method:'POST',headers,body:JSON.stringify({phone,role:'translator'})});
  const v=await (await fetch('/api/auth/verify',{method:'POST',headers,body:JSON.stringify({phone,role:'translator',code:'123456'})})).json();
  if(!v.token)return null;
  const s=HZ.load();s.token=v.token;s.session={phone,until:Date.now()+3600e3};s.completed[1]=true;HZ.save(s);
  await fetch('/api/dev/approve-translator',{method:'POST',headers:{Authorization:'Bearer '+v.token}});
  s.status='active_general';s.profile={nameFa:'آزمون',lastFa:'محلی'};HZ.save(s);return v.token;
}"""

async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    page = await context.new_page()
    await page.route(re.compile('https://(unpkg[.]com|cdn[.]|fonts[.]).*'), lambda route: route.abort())
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    await page.goto(BASE + '/translator/index.html')
    phone = '9' + str(random.randint(100000000, 999999999))
    token = await page.evaluate(LOGIN_JS, phone)
    assert token
    for mission in FIXTURES:
        response = await page.evaluate("""async ([token, mission]) => {
          const r=await fetch('/api/dev/missions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify(mission)});
          return r.status;
        }""", [token, mission])
        assert response == 200
    await page.goto(BASE + '/translator/app.html')
    await page.wait_for_function("() => document.querySelector('#missions-list .translator-empty-missions')")
    text = await page.locator('#missions-list').inner_text()
    assert 'Fixture Passenger' not in text and 'Fixture Place' not in text, text
    assert await page.locator('#day-bar').is_hidden()
    assert await page.locator('#translator-map-placeholder').is_visible()
    assert not errors, errors
    print(f'PASS [{width}]: no development fixture cards or map points appear')
    await context.close()

async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=['--no-sandbox'])
        try:
            await scenario(browser, 390)
            await scenario(browser, 1280)
        finally:
            await browser.close()

asyncio.run(main())
