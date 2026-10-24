# No calendar day/status may be inferred from development fixtures; only real reservations produce this schedule.
import asyncio, random
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS, SEED_JS

FIXTURES = [
  {'code': 'M-1', 'purpose': 'fixture', 'travelerName': 'Fixture Day A', 'place': 'Fixture Place A', 'startAt': '2026-11-01T15:00:00.000Z', 'total': 100, 'net': 80, 'status': 'accepted'},
  {'code': 'M-2', 'purpose': 'fixture', 'travelerName': 'Fixture Day B', 'place': 'Fixture Place B', 'startAt': '2026-11-03T09:00:00.000Z', 'total': 200, 'net': 160, 'status': 'accepted'},
]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        context = await browser.new_context(viewport={'width': 390, 'height': 900}, service_workers='block')
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto('http://127.0.0.1:8081/translator/index.html')
        token = await page.evaluate(LOGIN_JS, '9' + str(random.randint(100000000, 999999999)))
        assert token
        await page.evaluate(SEED_JS, [token, FIXTURES])
        await page.goto('http://127.0.0.1:8081/translator/app.html')
        await page.wait_for_function("() => document.querySelector('#missions-list .translator-empty-missions')")
        buttons = await page.locator('#day-bar button').all_text_contents()
        assert buttons == [], buttons
        assert await page.locator('#day-bar').is_hidden()
        mission_text = await page.locator('#missions-list').inner_text()
        schedule_text = await page.locator('#schedule-list').inner_text()
        assert 'Fixture Day' not in mission_text + schedule_text
        assert not errors, errors
        print('PASS: the schedule stays empty until reservation-backed server missions exist')
        await context.close()
        await browser.close()

asyncio.run(main())
