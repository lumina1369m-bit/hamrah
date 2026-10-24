"""Unsupported account features must not invent saved cards, identity review, or reminders.

Uses real traveler sessions. Historical local pending/verified/card flags must
not produce server-backed claims. Covers fa/en/ar, disabled request controls,
local profile edits, phone fallback, and switching languages on the same page.
"""
import asyncio
import re
from pathlib import Path
import secrets

from playwright.async_api import async_playwright, expect
from finish_flow_ui import api
from logout_sessions_ui import sign_in, seeded_context

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_account_truth'
COPY = {
    'fa': {
        'passport': 'بررسی گذرنامه هنوز فعال نیست؛ از این صفحه مدرکی برای بررسی ارسال نمی‌شود.',
        'cards': 'هیچ کارت بانکی به این حساب متصل نشده است.',
        'cards_note': 'ذخیره و اتصال کارت بانکی هنوز فعال نیست. پرداخت رزروها از بخش فاکتور انجام می‌شود.',
        'disabled': 'فعلاً غیرفعال',
        'local': 'نام و عکس پروفایل فقط در همین مرورگر ذخیره می‌شوند.',
        'gender': 'تغییر جنسیت از این صفحه هنوز فعال نیست؛ درخواستی برای پشتیبانی ثبت نمی‌شود.',
        'contact': 'تغییر شمارهٔ ورود از این صفحه هنوز فعال نیست.',
        'reminders_status': 'در این نسخه در دسترس نیست',
        'reminders_note': 'در این نسخه اعلان خودکار برای یادآوری رزروها ارسال نمی‌شود.',
    },
    'en': {
        'passport': 'Passport review is not available yet; no document is submitted for review from this page.',
        'cards': 'No bank card is linked to this account.',
        'cards_note': 'Saving or linking bank cards is not available yet. Pay for bookings from the invoice.',
        'disabled': 'Currently unavailable',
        'local': 'Your profile name and photo are saved only in this browser.',
        'gender': 'Gender changes are not available here yet; no request is sent to support.',
        'contact': 'Changing your sign-in phone number is not available here yet.',
        'reminders_status': 'Not available in this version',
        'reminders_note': 'This version does not send automatic booking reminder notifications.',
    },
    'ar': {
        'passport': 'مراجعة جواز السفر غير متاحة حالياً؛ لا تُرسل أي وثيقة للمراجعة من هذه الصفحة.',
        'cards': 'لا توجد بطاقة بنكية مرتبطة بهذا الحساب.',
        'cards_note': 'حفظ البطاقات البنكية أو ربطها غير متاح حالياً. يتم دفع الحجوزات من الفاتورة.',
        'disabled': 'غير متاح حالياً',
        'local': 'يُحفظ اسم ملفك الشخصي وصورتك في هذا المتصفح فقط.',
        'gender': 'تغيير الجنس غير متاح هنا حالياً؛ لا يُرسل أي طلب إلى الدعم.',
        'contact': 'تغيير رقم هاتف الدخول غير متاح هنا حالياً.',
        'reminders_status': 'غير متاحة في هذا الإصدار',
        'reminders_note': 'لا يرسل هذا الإصدار إشعارات تلقائية لتذكيرك بالحجوزات.',
    },
}


async def check_copy(page, lang):
    texts = COPY[lang]
    for selector, key in [('#ac-passport-box', 'passport'), ('#ac-cards', 'cards'),
                          ('#ac-cards-note', 'cards_note'), ('#ac-profile-local-note', 'local'),
                          ('#ac-gender-note', 'gender'), ('#ac-contact-note', 'contact'),
                          ('#ac-reminders-status', 'reminders_status'), ('#ac-reminders-note', 'reminders_note')]:
        await expect(page.locator(selector)).to_have_text(texts[key])
    for selector, note in [('#ac-gender-btn', 'ac-gender-note'), ('#ac-contact-btn', 'ac-contact-note')]:
        await expect(page.locator(selector)).to_be_disabled()
        await expect(page.locator(selector)).to_have_text(texts['disabled'])
        await expect(page.locator(selector)).to_have_attribute('aria-describedby', note)
    assert await page.locator('#ac-passport-box input, #ac-passport-box button, #ac-cards button').count() == 0


async def scenario(browser, lang):
    setup = await browser.new_context()
    ctx, page, errors = None, None, []
    try:
        session = await sign_in(setup.request, '9' + str(secrets.randbelow(900000000) + 100000000))
        ctx, page = await seeded_context(browser, session, lang, errors)
        writes = []
        page.on('request', lambda r: writes.append(r.url) if '/api/' in r.url and r.method in ['POST', 'PUT', 'PATCH', 'DELETE'] else None)
        for flag in [None, 'pending', 'verified']:
            await page.evaluate("""flag => {
                const u = JSON.parse(localStorage.getItem('hamzaban.user.v1'));
                u.passport = flag; u.verified = flag === 'verified';
                u.photo = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/nZkAAAAASUVORK5CYII=';
                u.cardsRemoved = flag === 'verified' ? ['c1'] : [];
                localStorage.setItem('hamzaban.user.v1', JSON.stringify(u));
            }""", flag)
            before = await page.evaluate("() => localStorage.getItem('hamzaban.user.v1')")
            await page.reload()
            await page.locator('nav a[data-nav=account]').click()
            await check_copy(page, lang)
            await expect(page.locator('#ac-contact')).to_have_text(session['user']['phone'])
            await expect(page.locator('#ac-avatar img')).to_have_attribute('src', re.compile('^data:image/png;base64,'))
            assert await page.evaluate("() => localStorage.getItem('hamzaban.user.v1')") == before
        # Synthetic clicks must not revive the old 'request submitted' handlers.
        await page.evaluate("""() => {
            window.accountToasts = [];
            const old = window.showAppToast;
            window.showAppToast = (message, icon) => { accountToasts.push(message); old(message, icon); };
            ['ac-gender-btn','ac-contact-btn'].forEach(id => document.getElementById(id)
                .dispatchEvent(new MouseEvent('click', {bubbles:true})));
        }""")
        assert await page.evaluate('() => accountToasts') == []
        assert writes == [], writes
        # Legitimate local editing is retained and clearly labelled as local.
        await page.locator('#ac-name').fill('Sara')
        await page.locator('#ac-last').fill('Karimi')
        await page.locator('#ac-save').click()
        await expect(page.locator('#ac-fullname')).to_have_text('Sara Karimi')
        profile = await page.evaluate("() => JSON.parse(localStorage.getItem('hamzaban.user.v1'))")
        assert profile['name'] == 'Sara' and profile['authUserId'] == session['user']['id']
        assert profile['phone'] == session['user']['phone'] and profile['gender'] == 'مرد'
        await check_copy(page, lang)
        for selected in ['en', 'ar', 'fa', lang]:
            await page.locator('#hz-lang-select').select_option(selected)
            await check_copy(page, selected)
        assert writes == [], writes
        await api(setup.request, 'GET', '/auth/me', session['token'])
        assert not errors, errors
        print(f'PASS [{lang}]: local passport flags cannot create verification/review; no demo cards, fake support requests, or always-on reminder claim; local edits and language switching work')
    except Exception:
        print('JavaScript errors:', errors)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        if page:
            await page.screenshot(path=str(ARTIFACTS / f'account-{lang}.png'), full_page=True)
        raise
    finally:
        if ctx:
            await ctx.close()
        await setup.close()


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        for lang in ['fa', 'en', 'ar']:
            await scenario(browser, lang)
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
