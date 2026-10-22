"""Payment clicks are not success: rejected, disconnected and pending requests.

Uses actual server bookings/payments. Only the disconnected request is aborted;
for the slow-success test the original request is delayed then sent to the server.
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking
from booking_options_ui import login, translator

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_settlement_failure'


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
        page = await ctx.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        release = asyncio.Event()
        try:
            await api(ctx.request, 'POST', '/dev/offline-all')
            config = await api(ctx.request, 'GET', '/config')
            assert config['payments']['CASH'] and not config['payments']['ONLINE'], config['payments']
            ptok, phone = await login(ctx.request, 'traveler')
            ttok = await translator(ctx.request, 'male')
            created = await api(ctx.request, 'POST', '/traveler/bookings', ptok,
                                {'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa',
                                 'category': 'general', 'hours': 1, 'car': False,
                                 'place': 'آزمون شکست پرداخت', 'traveler_name': 'علی رضایی'}, status=201)
            bid = created['id']
            offers = await api(ctx.request, 'GET', '/translator/offers', ttok)
            await api(ctx.request, 'POST', f"/translator/offers/{offers['offers'][0]['id']}/accept", ttok)
            await api(ctx.request, 'POST', f'/translator/missions/{bid}/verify-code', ttok,
                      {'code': created['service_code']})
            await api(ctx.request, 'POST', f'/traveler/bookings/{bid}/finish', ptok)
            user = {'name': 'علی', 'last': 'رضایی', 'gender': 'مرد', 'phone': phone}
            await ctx.add_init_script(
                'localStorage.setItem("hamzaban.token.v1", ' + json.dumps(ptok) + ');'
                'localStorage.setItem("hamzaban.user.v1", ' + json.dumps(json.dumps(user)) + ');'
                'localStorage.setItem("hamzaban_lang", "fa");')
            await ctx.route('https://nominatim.openstreetmap.org/**',
                            lambda route: route.fulfill(json={'display_name': 'تهران، آزمون پرداخت'}))
            await ctx.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
            await page.goto(BASE + '/traveler/app.html')
            await expect(page.locator('#stage-6')).to_be_visible()
            await page.evaluate("""() => {
              window.paymentToasts = [];
              const show = window.showAppToast;
              window.showAppToast = (message, icon) => { paymentToasts.push(message); show(message, icon); };
            }""")
            button = page.locator('#btn-settle-return')
            path = f'**/api/traveler/bookings/{bid}/payment'

            async def unchanged():
                await expect(page.locator('#stage-6')).to_be_visible()
                await expect(button).to_be_enabled()
                assert not await page.evaluate("() => paymentToasts.some(t => t.includes('پرداخت انجام شد'))")
                current = await booking(ctx.request, ptok, bid)
                assert current['status'] == 'finished' and current['pay_state'] is None, current
                assert current['total'] == created['total']

            # Real backend rejection of the intentionally disabled online method.
            await page.locator('#pay-method-online').click()
            async with page.expect_response(lambda r: r.url.endswith(f'/{bid}/payment')) as result:
                await button.click()
            response = await result.value
            assert response.status == 409, await response.text()
            await expect(page.locator('#toast-text')).to_have_text('این روش پرداخت فعال نیست.')
            await unchanged()
            print('PASS: rejected online payment keeps the invoice open, with no false success')

            await page.locator('#pay-method-cash').click()
            async def disconnected(route):
                await route.abort('internetdisconnected')
            await page.route(path, disconnected)
            await button.click()
            await expect(page.locator('#toast-text')).to_have_text('انجام نشد. دوباره تلاش کنید.')
            await unchanged()
            await page.unroute(path, disconnected)
            print('PASS: disconnected payment stays retryable without changing server payment state')

            await page.evaluate("() => localStorage.removeItem('hamzaban.token.v1')")
            await button.click()
            await expect(page.locator('#toast-text')).to_have_text('برای ثبت پرداخت، ورود و رزرو معتبر لازم است.')
            await unchanged()
            await page.evaluate('(token) => localStorage.setItem("hamzaban.token.v1", token)', ptok)

            # Hold the real cash request in flight. Even a synthetic duplicate click
            # must be ignored by the guard, independent of HTML's disabled behavior.
            requests = []
            arrived = asyncio.Event()
            async def delayed(route):
                requests.append(route.request.url)
                arrived.set()
                await release.wait()
                await route.continue_()
            await page.route(path, delayed)
            await button.click()
            await expect(button).to_be_disabled()
            await expect(button).to_have_attribute('aria-busy', 'true')
            await asyncio.wait_for(arrived.wait(), timeout=20)
            await page.evaluate("() => document.getElementById('btn-settle-return').dispatchEvent(new MouseEvent('click', {bubbles: true}))")
            await expect(page.locator('#stage-6')).to_be_visible()
            assert len(requests) == 1, requests
            pending = await booking(ctx.request, ptok, bid)
            assert pending['pay_state'] is None
            assert not await page.evaluate("() => paymentToasts.some(t => t.includes('پرداخت انجام شد'))")
            release.set()
            await expect(page.locator('#location-picker-bar')).to_be_visible()
            await expect(page.locator('#stage-6')).to_be_hidden()
            await expect(button).to_be_enabled()
            final = await booking(ctx.request, ptok, bid)
            assert final['status'] == 'finished' and final['pay_state'] == 'awaiting_cash', final
            assert len(requests) == 1
            assert not await page.evaluate("() => paymentToasts.some(t => t.includes('پرداخت انجام شد'))")
            assert await page.evaluate("() => paymentToasts.some(t => t.includes('با تأیید مترجم'))")
            assert not errors, errors
            print('PASS: exactly one request during pending payment; cash success awaits translator confirmation')
        except Exception:
            print('JavaScript errors:', errors)
            print('Toasts:', await page.evaluate('() => window.paymentToasts || []'))
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            try:
                await page.screenshot(path=str(ARTIFACTS / 'payment-failure.png'), full_page=True)
            except Exception:
                pass
            raise
        finally:
            release.set()
            await ctx.close()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
