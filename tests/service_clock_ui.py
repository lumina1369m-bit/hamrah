"""Reload/reopen regression for server-origin service time, extensions and invoice.

The browser clock advances 40 minutes; all APIs and the server clock remain real.
No real waiting or test-only mutation of the database/start timestamp is needed.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking, arrive_and_start
from booking_options_ui import login, translator

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_service_clock'
DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def fa(value):
    return str(value).translate(DIGITS)


async def seconds(page):
    text = await page.locator('#live-timer-val').inner_text()
    parts = text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')).split(':')
    h, m, s = map(int, parts)
    return h * 3600 + m * 60 + s


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
        page = await ctx.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        admin_token = None
        original_rates = None
        try:
            await api(ctx.request, 'POST', '/dev/offline-all')
            ptok, phone = await login(ctx.request, 'traveler')
            ttok = await translator(ctx.request, 'male')
            user = {'name': 'علی', 'last': 'رضایی', 'gender': 'مرد', 'phone': phone}
            await ctx.add_init_script(
                'localStorage.setItem("hamzaban.token.v1", ' + json.dumps(ptok) + ');'
                'localStorage.setItem("hamzaban.user.v1", ' + json.dumps(json.dumps(user)) + ');'
                'localStorage.setItem("hamzaban_lang", "fa");')
            await ctx.route('https://nominatim.openstreetmap.org/**',
                            lambda route: route.fulfill(json={'display_name': 'تهران، آزمون زمان خدمت'}))
            await ctx.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
            await page.goto(BASE + '/traveler/app.html')
            # A stale cache entry alone must never resume a service for this user.
            await page.evaluate("""() => localStorage.setItem('hamzaban.bookings.v1', JSON.stringify([
              {serverId: 999999999, srvStatus: 'matched', serviceStarted: true,
               serviceStartedAt: new Date(Date.now()-60000).toISOString(), hoursNum: 1}
            ]))""")
            await page.reload()
            await page.wait_for_function('() => window.hzBookingsSynced === true')
            await page.wait_for_timeout(1500)  # allow the once-per-second restoration check
            await expect(page.locator('#stage-5')).to_be_hidden()
            await expect(page.locator('#location-picker-bar')).to_be_visible()
            await page.evaluate("() => localStorage.removeItem('hamzaban.bookings.v1')")

            created = await api(ctx.request, 'POST', '/traveler/bookings', ptok,
                                {'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa',
                                 'category': 'medical', 'hours': 1, 'car': False,
                                 'place': 'آزمون بازیابی تایمر', 'traveler_name': 'علی رضایی'}, status=201)
            bid = created['id']
            assert created['service_started_at'] is None and created['finished_at'] is None
            offers = await api(ctx.request, 'GET', '/translator/offers', ttok)
            await api(ctx.request, 'POST', f"/translator/offers/{offers['offers'][0]['id']}/accept", ttok)
            await arrive_and_start(ctx.request, bid, ttok, created['service_code'])
            started = await booking(ctx.request, ptok, bid)
            origin = started['service_started_at']
            assert origin
            origin_date = datetime.fromisoformat(origin.replace('Z', '+00:00'))
            await page.clock.install(time=origin_date + timedelta(minutes=40))
            await page.reload()
            await expect(page.locator('#stage-5')).to_be_visible()
            await expect(page.locator('#of-hours')).to_contain_text('۱ ساعت')
            await expect(page.locator('#expiry-warning')).to_be_visible()
            elapsed = await seconds(page)
            assert 2400 <= elapsed <= 2420, elapsed
            print('PASS: timer restores the server start (40 elapsed minutes), not zero; duration is 1 hour')

            # Reopening with no cached booking must yield the same time and duration.
            await page.evaluate("() => localStorage.removeItem('hamzaban.bookings.v1')")
            await page.reload()
            await expect(page.locator('#stage-5')).to_be_visible()
            await expect(page.locator('#of-hours')).to_contain_text('۱ ساعت')
            after_reload = await seconds(page)
            assert elapsed <= after_reload <= elapsed + 20, (elapsed, after_reload)

            async with page.expect_response(lambda r: r.url.endswith(f'/{bid}/extend') and r.request.method == 'POST') as result:
                await page.locator('#btn-extend-one-hour').click()
            response = await result.value
            assert response.status == 202, await response.text()
            extension = await response.json()
            await page.reload()
            await expect(page.locator('#stage-5')).to_be_visible()
            await expect(page.locator('#btn-extend-one-hour')).to_be_disabled()
            await expect(page.locator('#of-hours')).to_contain_text('۱ ساعت')
            await api(ctx.request, 'POST', f"/translator/extensions/{extension['id']}/accept", ttok)
            extended = await booking(ctx.request, ptok, bid)
            assert extended['hours'] == 2 and extended['service_started_at'] == origin
            await page.reload()
            await expect(page.locator('#stage-5')).to_be_visible()
            await expect(page.locator('#of-hours')).to_contain_text('۲ ساعت')
            await expect(page.locator('#expiry-warning')).to_be_hidden()
            assert after_reload <= await seconds(page) <= after_reload + 30
            print('PASS: pending extension survives reload; accepted duration restores without resetting time')

            # Finish requests also survive reopening; the traveler can still reject.
            await api(ctx.request, 'POST', f'/translator/missions/{bid}/finish', ttok, status=202)
            await page.reload()
            await expect(page.locator('#finish-request-banner')).to_be_visible()
            async with page.expect_response(lambda r: r.url.endswith(f'/{bid}/finish-reject')) as result:
                await page.locator('#btn-reject-finish').click()
            assert (await result.value).status == 200
            await expect(page.locator('#finish-request-banner')).to_be_hidden()

            # A new live tariff must not recalculate the agreed invoice on reopen.
            original_rates = (await api(ctx.request, 'GET', '/config'))['tariffs']['hourly']
            admin_token = (await api(ctx.request, 'POST', '/admin/login',
                                     data={'password': 'test-admin-pass'}))['token']
            new_rates = {**original_rates, 'medical': original_rates['medical'] + 333333}
            await api(ctx.request, 'PUT', '/admin/settings', admin_token, {'hourly_tariffs': new_rates})
            async with page.expect_response(lambda r: r.url.endswith(f'/{bid}/finish') and r.request.method == 'POST') as result:
                await page.locator('#btn-finish-service').click()
            assert (await result.value).status == 200
            await expect(page.locator('#stage-6')).to_be_visible()
            final = await booking(ctx.request, ptok, bid)
            assert final['service_started_at'] == origin and final['finished_at'] is not None
            assert final['total'] == extended['total']
            await page.evaluate("() => localStorage.removeItem('hamzaban.bookings.v1')")
            await page.reload()
            await expect(page.locator('#stage-6')).to_be_visible()
            for key, selector in [('base', '#inv-base'), ('tax', '#inv-tax'), ('total', '#inv-total')]:
                await expect(page.locator(selector)).to_have_text(fa(f"{final[key]:,}") + ' تومان')
            await expect(page.locator('#inv-label')).to_contain_text('۲ ساعت')
            assert not errors, errors
            print('PASS: finished service reopens its invoice with the full agreed amount, despite changed tariffs')
        except Exception:
            print('JavaScript errors:', errors)
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            try:
                await page.screenshot(path=str(ARTIFACTS / 'service-clock.png'), full_page=True)
            except Exception:
                pass
            raise
        finally:
            if admin_token and original_rates:
                await api(ctx.request, 'PUT', '/admin/settings', admin_token, {'hourly_tariffs': original_rates})
            await ctx.close()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
