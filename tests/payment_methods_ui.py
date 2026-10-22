"""Server-owned payment choices in both invoice and booking-list modal.

Changes only a disposable test server's settings and restores them in finally.
No payment is sent: also checks blocked/malformed configuration fails closed.
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking
from booking_options_ui import login, translator

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_payment_methods'


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
        page = await ctx.new_page()
        page.set_default_timeout(20000)
        errors, payments = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: payments.append(r.url) if r.url.endswith('/payment') and r.method == 'POST' else None)
        admin = None
        original = None
        try:
            await api(ctx.request, 'POST', '/dev/offline-all')
            original = (await api(ctx.request, 'GET', '/config'))['payments']
            admin = (await api(ctx.request, 'POST', '/admin/login', data={'password': 'test-admin-pass'}))['token']
            ptok, phone = await login(ctx.request, 'traveler')
            ttok = await translator(ctx.request, 'male')
            created = await api(ctx.request, 'POST', '/traveler/bookings', ptok,
                                {'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa', 'hours': 1,
                                 'place': 'آزمون روش‌های پرداخت', 'traveler_name': 'علی رضایی'}, status=201)
            bid = created['id']
            offers = await api(ctx.request, 'GET', '/translator/offers', ttok)
            await api(ctx.request, 'POST', f"/translator/offers/{offers['offers'][0]['id']}/accept", ttok)
            await api(ctx.request, 'POST', f'/translator/missions/{bid}/verify-code', ttok, {'code': created['service_code']})
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

            async def settings(cash, online):
                await api(ctx.request, 'PUT', '/admin/settings', admin,
                          {'cash_enabled': int(cash), 'online_enabled': int(online)})

            async def refresh():
                await page.locator('#btn-refresh-payment-methods').click()
                await expect(page.locator('#btn-refresh-payment-methods')).to_be_enabled()

            for cash, online in [(True, False), (False, True), (True, True), (False, False)]:
                await settings(cash, online)
                await refresh()
                for method, enabled in [('cash', cash), ('online', online)]:
                    await expect(page.locator('#pay-method-' + method)).to_be_visible(visible=enabled)
                    await expect(page.locator('#pay-method-' + method)).to_be_enabled(enabled=enabled)
                await expect(page.locator('#btn-settle-return')).to_be_enabled(enabled=cash or online)
                if cash:
                    await page.locator('#pay-method-cash').click()
                    await expect(page.locator('#pay-method-online')).to_be_visible(visible=online)
                if cash and online:
                    await refresh()
                    assert await page.evaluate('() => window.payChoice') == 'cash', 'Refresh must preserve an allowed selection'
                choice = await page.evaluate('() => window.payChoice')
                assert (cash if choice == 'cash' else online if choice == 'online' else not cash and not online)
                if not cash and not online:
                    await expect(page.locator('#payment-method-status')).to_have_text('در حال حاضر هیچ روش پرداختی فعال نیست.')
                else:
                    await expect(page.locator('#pay-method-' + choice)).to_have_attribute('aria-pressed', 'true')
                # The list modal must fetch again, not reuse its first configuration.
                await page.locator('nav a[data-nav=bookings]').click()
                await page.locator('#bk-tabs').get_by_role('button', name='در جریان', exact=True).click()
                await page.locator('#bk-list').get_by_role('button', name='پرداخت', exact=True).click()
                modal = page.locator('#bk-modal')
                await expect(modal).to_be_visible()
                assert await modal.get_by_role('button', name='نقدی پرداخت کردم', exact=True).count() == int(cash)
                assert await modal.get_by_role('button', name='پرداخت آنلاین', exact=True).count() == int(online)
                await modal.get_by_role('button', name='انصراف', exact=True).click()
                await page.locator('nav a[data-nav=map]').click()
                print(f'PASS: cash={cash}, online={online}; invoice and freshly opened modal agree')

            # A method can be disabled while its list modal is already open.
            await settings(True, False)
            await page.locator('nav a[data-nav=bookings]').click()
            await page.locator('#bk-tabs').get_by_role('button', name='در جریان', exact=True).click()
            await page.locator('#bk-list').get_by_role('button', name='پرداخت', exact=True).click()
            await expect(page.locator('#bk-modal')).to_be_visible()
            await settings(False, False)
            await page.locator('#bk-modal').get_by_role('button', name='نقدی پرداخت کردم', exact=True).click()
            await expect(page.locator('#toast-text')).to_have_text('این روش پرداخت فعال نیست.')
            await page.locator('nav a[data-nav=map]').click()
            assert not payments
            print('PASS: disabling cash while its modal is open blocks the pending attempt without any payment POST')

            # A failed pre-payment config request cannot leave stale active buttons.
            await settings(True, False)
            await refresh()
            await expect(page.locator('#btn-settle-return')).to_be_enabled()
            async def disconnected(route):
                await route.abort('internetdisconnected')
            await page.route('**/api/config', disconnected)
            await page.locator('#btn-settle-return').click()
            await expect(page.locator('#toast-text')).to_have_text('روش‌های پرداخت دریافت نشد. دوباره تلاش کنید.')
            await expect(page.locator('#stage-6')).to_be_visible()
            await expect(page.locator('#payment-method-status')).to_have_text('روش‌های پرداخت دریافت نشد. دوباره تلاش کنید.')
            await expect(page.locator('#btn-settle-return')).to_be_disabled()
            await expect(page.locator('#pay-method-cash')).to_be_hidden()
            await page.unroute('**/api/config', disconnected)
            async def malformed(route):
                await route.fulfill(json={'payments': {'CASH': 'false', 'ONLINE': 'true'}})
            await page.route('**/api/config', malformed)
            await refresh()
            await expect(page.locator('#btn-settle-return')).to_be_disabled()
            await expect(page.locator('#payment-method-status')).to_have_text('روش‌های پرداخت دریافت نشد. دوباره تلاش کنید.')
            await page.unroute('**/api/config', malformed)
            await settings(True, False)
            await refresh()
            await expect(page.locator('#pay-method-cash')).to_be_visible()
            await expect(page.locator('#btn-settle-return')).to_be_enabled()
            assert await page.evaluate('() => window.payChoice') == 'cash'
            assert not payments, payments
            final = await booking(ctx.request, ptok, bid)
            assert final['pay_state'] is None and final['total'] == created['total'], final
            assert not errors, errors
            print('PASS: unavailable/malformed configuration blocks payment; retry restores cash without sending a charge')
        except Exception:
            print('JavaScript errors:', errors)
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            try:
                await page.screenshot(path=str(ARTIFACTS / 'payment-methods.png'), full_page=True)
            except Exception:
                pass
            raise
        finally:
            if admin and original:
                await api(ctx.request, 'PUT', '/admin/settings', admin,
                          {'cash_enabled': int(original['CASH']), 'online_enabled': int(original['ONLINE'])})
            await ctx.close()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
