"""The traveler translators screen must not invent counts or imply unverified professional status."""
import asyncio
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api
from logout_sessions_ui import sign_in
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_traveler_translators'
COPY = {
    'fa': {
        'subheading': 'اطلاعات مترجمان',
        'heading': 'حریم خصوصی مترجمان',
        'note': 'برای حفظ حریم خصوصی، هویت و موقعیت دقیق مترجمان پیش از تطبیق نمایش داده نمی‌شود. مترجم فقط پس از پذیرش درخواست شما معرفی می‌شود.',
        'unsupported_subheading': 'شبکه‌ی مترجمان همزمان و حرفه‌ای شما',
    },
    'en': {
        'subheading': 'Interpreter information',
        'heading': 'Translator privacy',
        'note': "To protect privacy, translators' identity and exact location are not shown before matching. A translator is introduced only after accepting your request.",
        'unsupported_subheading': 'Your network of professional interpreters',
    },
    'ar': {
        'subheading': 'معلومات المترجمين',
        'heading': 'خصوصية المترجمين',
        'note': 'لحماية الخصوصية، لا تُعرض هوية المترجمين ومواقعهم الدقيقة قبل التطابق. لا يُعرَّف المترجم إلا بعد قبول طلبك.',
        'unsupported_subheading': 'شبكة المترجمين المحترفين الخاصة بك',
    },
}


async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    await context.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
    await context.route('https://nominatim.openstreetmap.org/**', lambda route: route.abort())
    page = await context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    try:
        await api(context.request, 'POST', '/dev/offline-all')
        phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        session = await sign_in(context.request, phone)
        await page.goto(BASE + '/traveler/index.html')
        profile = {
            'name': 'Ali', 'last': 'Rezaei', 'gender': 'مرد',
            'phone': session['user']['phone'], 'authUserId': session['user']['id'],
        }
        await page.evaluate('''([token, profile]) => {
            localStorage.setItem('hamzaban.token.v1', token);
            localStorage.setItem('hamzaban.user.v1', JSON.stringify(profile));
            localStorage.setItem('hamzaban.bookings.v1', '[]');
            localStorage.setItem('hamzaban_lang', 'fa');
        }''', [session['token'], profile])
        await page.goto(BASE + '/traveler/app.html')
        await page.wait_for_function('() => window.hzBookingsSynced === true')
        await expect(page.locator('nav a[data-nav="translators"]')).to_be_visible()
        for language, copy in COPY.items():
            if language != 'fa':
                await page.locator('nav a[data-nav="account"]').click()
                await page.locator('#hz-lang-select').select_option(language)
            await page.locator('nav a[data-nav="translators"]').click()
            screen = page.locator('#scr-translators')
            await expect(screen).to_be_visible()
            await expect(screen.locator('.scr-sub')).to_have_text(copy['subheading'])
            await expect(screen.locator('.tr-card > span')).to_have_text(copy['heading'])
            await expect(screen.locator('#translator-privacy-note')).to_have_text(copy['note'])
            await expect(screen.locator('.tr-count')).to_have_count(0)
            text = await screen.inner_text()
            assert copy['unsupported_subheading'] not in text, 'an unverified professional-network claim remains on the translators screen'
            assert 'مترجمان آنلاین در محدوده‌ی شما' not in text
            assert 'online interpreters in your area' not in text
            assert '۴' not in text and '4' not in text and '٤' not in text, 'a fixed interpreter count remains on the translators screen'
            print(f'PASS [{width}/{language}]: no fabricated count or unverified professional-network claim')
        assert not errors, errors
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
    print('RESULT: PASS (2/2 viewports; 6 language/viewport combinations)')


asyncio.run(main())
