"""Translator workspace must use real server offers, never a canned dispatch simulation."""
import asyncio
import os
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from hz_api import LOGIN_JS

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_dispatch_truth'
FORBIDDEN = (
    'اعزام فوری پزشکی', 'MAT-030', 'بیمارستان دی', 'عبدالرحمن السالم',
    '۲,۳۵۰,۰۰۰', '2,350,000', '۱.۸ کیلومتر', '۵ دقیقه',
    'تماس با مسافر (+۹۶۴)', 'مسیریابی با نشان / بلد',
    'رسیده به محل بیمارستان دی', 'تسویه خودکار پس از پایان مأموریت',
    'در انتظار درخواست بعدی سامانه دیسپچ', 'پیشنهاد جدید اعزام بارگذاری شد',
    'اعزام‌های فوری فرودگاهی و بیمارستانی',
)
FAKE_IDS = (
    'dispatch-view-wrapper', 'dispatch-offer-card', 'inline-active-dispatch-card',
    'dispatch-empty-card', 'countdown-number', 'inline-confirm-arrival-btn',
    'mission-live-timer',
)
FAKE_HANDLERS = (
    'handleAcceptMission', 'handleRejectMission', 'revertToDispatchOffer',
    'resetDispatchDemo', 'callPassengerSecurely', 'openNavigatorApp',
    'confirmArrivalAtDestination',
)


async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    page = await context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    try:
        await page.goto(BASE + '/translator/index.html')
        phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        token = await page.evaluate(LOGIN_JS, phone)
        assert token, 'translator session was not established'
        await page.goto(BASE + '/translator/app.html')
        workspace = page.locator('#view-workspace')
        await expect(workspace).to_be_visible()
        await expect(workspace.locator('#calendar-section')).to_be_visible()
        await expect(workspace.locator('#offers-box')).to_be_attached()
        await expect(workspace.locator('#missions-list')).to_be_attached()

        text = await workspace.inner_text()
        for value in FORBIDDEN:
            assert value not in text, f'canned dispatch data remains in workspace: {value}'
        for selector in FAKE_IDS:
            assert await page.locator('#' + selector).count() == 0, f'legacy dispatch element remains: #{selector}'
        handlers = await page.evaluate('(names) => names.filter(name => typeof window[name] === "function")', list(FAKE_HANDLERS))
        assert not handlers, f'fake dispatch handlers remain: {handlers}'
        await expect(page.locator('#shift-status-desc')).not_to_contain_text('اعزام فوری')
        await page.evaluate('''() => {
            window.__dispatchToasts = [];
            const original = window.showToast;
            window.showToast = function (message, ...args) {
                window.__dispatchToasts.push(String(message));
                return original.call(this, message, ...args);
            };
        }''')
        if width == 390:
            # The former canned countdown falsely announced a rejection 14 seconds after load.
            await page.wait_for_timeout(16000)
            toasts = await page.evaluate('() => window.__dispatchToasts')
            assert not any('مأموریت رد شد' in message or 'دیسپچ' in message for message in toasts), toasts
        assert not errors, errors
        print(f'PASS [{width}]: no canned mission/tracking/actions; live offers and mission containers remain')
    except Exception:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(ARTIFACTS / f'failure-{width}.png'), full_page=True)
            (ARTIFACTS / f'failure-{width}.html').write_text(await page.content())
        except Exception:
            pass
        raise
    finally:
        await context.close()


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=['--no-sandbox'])
        try:
            await scenario(browser, 390)
            await scenario(browser, 1280)
        finally:
            await browser.close()
    print('RESULT: PASS (2/2 viewports)')


asyncio.run(main())
