# توسعه-only mission rows are fixtures, not reservations; the translator UI must never render them as real work.
import asyncio, random, sys
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS, SEED_JS

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
FIXTURES = [
  {'code': 'M-1', 'purpose': 'general', 'travelerName': 'Fixture Traveler A', 'place': 'Fixture Place A', 'startAt': '2026-11-01T09:00:00.000Z', 'total': 3200000, 'net': 2560000, 'status': 'accepted'},
  {'code': 'M-2', 'purpose': 'medical', 'travelerName': 'Fixture Traveler B', 'place': 'Fixture Place B', 'startAt': '2026-11-02T09:00:00.000Z', 'total': 900000, 'net': 720000, 'status': 'accepted'},
]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        context = await browser.new_context(viewport={'width': 390, 'height': 900}, service_workers='block')
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(BASE + '/translator/index.html')
        token = await page.evaluate(LOGIN_JS, '9' + str(random.randint(100000000, 999999999)))
        assert token, 'translator API login failed'
        await page.evaluate(SEED_JS, [token, FIXTURES])
        await page.goto(BASE + '/translator/app.html')
        await page.wait_for_function("() => document.querySelector('#missions-list .translator-empty-missions')")
        cards = await page.locator('#missions-list').inner_text()
        assert 'Fixture Traveler' not in cards and 'Fixture Place' not in cards, cards
        assert 'فعلاً مأموریت پذیرفته‌شده‌ای ندارید' in cards, cards
        assert await page.locator('#day-bar button').count() == 0
        assert await page.locator('#day-bar').is_hidden()
        schedule_text = await page.locator('#schedule-list').inner_text()
        assert 'Fixture Traveler' not in schedule_text and 'Fixture Place' not in schedule_text
        assert not errors, errors
        print('PASS: development-only mission fixtures are excluded; only reservation-backed mission cards reach the translator workspace')
        await context.close()
        await browser.close()

asyncio.run(main())
