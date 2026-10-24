"""Traveler sign-in page copy must describe requests, not guaranteed interpreter availability."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_traveler_landing_claims'
COPY = {
    'fa': {
        'brand_tagline': 'ثبت درخواست و رزرو مترجم حضوری',
        'hero_eyebrow': 'درخواست مترجم برای سفر و کار',
        'hero_title': 'ثبت درخواست مترجم حضوری',
        'hero_desc': 'زبان‌ها، نوع خدمت و محل ملاقات را مشخص کنید و درخواست فوری یا رزرو زمان‌دار ثبت کنید. پذیرش درخواست به در دسترس بودن مترجم بستگی دارد.',
        'f2_title': 'انتخاب زبان‌ها',
        'f2_desc': 'زبان مبدأ و مقصد را هنگام ثبت درخواست انتخاب کنید.',
        'f3_title': 'معرفی مترجم پس از پذیرش',
        'f3_desc': 'مشخصات مترجم پس از پذیرش درخواست نمایش داده می‌شود.',
        'trust_verified': 'تطبیق بر اساس درخواست',
        'trust_verified_sub': 'زبان‌ها و نوع خدمت را مشخص کنید',
        'trust_nda': 'رزرو زمان‌دار',
        'trust_nda_sub': 'زمان آینده را برای درخواست انتخاب کنید',
        'mobile_card_desc': 'درخواست فوری یا زمان‌دار ثبت کنید؛ پذیرش به در دسترس بودن مترجم بستگی دارد.',
        'card_desc': 'برای ثبت درخواست مترجم حضوری، با شماره همراه وارد شوید.',
        'otp_note': 'برای ورود با شماره همراه، کد یک‌بارمصرف لازم است؛ ورود با ایمیل فعلاً فعال نیست.',
        'otp_instruction': 'کد شش‌رقمی مرتبط با شماره بالا را وارد کنید:',
        'auth_success': 'ورود موفق بود؛ صفحهٔ درخواست باز می‌شود.',
        'footer_rights': 'هم‌زبان • ثبت درخواست و رزرو مترجم حضوری',
    },
    'en': {
        'brand_tagline': 'In-person interpreter requests and bookings',
        'hero_eyebrow': 'For travel and work',
        'hero_title': 'Request an in-person interpreter',
        'hero_desc': 'Choose the languages, service type, and meeting point, then submit an instant request or a scheduled booking. Acceptance depends on interpreter availability.',
        'f2_title': 'Choose languages',
        'f2_desc': 'Select the source and destination languages for your request.',
        'f3_title': 'Interpreter details after acceptance',
        'f3_desc': 'Interpreter details are shown after your request is accepted.',
        'trust_verified': 'Matching based on your request',
        'trust_verified_sub': 'Choose your languages and service type',
        'trust_nda': 'Scheduled booking',
        'trust_nda_sub': 'Choose a future time for your request',
        'mobile_card_desc': 'Submit an instant or scheduled request. Acceptance depends on interpreter availability.',
        'card_desc': 'Sign in with your mobile number to submit an interpreter request.',
        'otp_note': 'Phone sign-in requires a one-time code; email sign-in is not available yet.',
        'otp_instruction': 'Enter the six-digit code for the phone number above.',
        'auth_success': 'Sign-in successful. Opening the request page...',
        'footer_rights': 'Hamzaban • In-person interpreter requests and bookings',
    },
    'ar': {
        'brand_tagline': 'طلبات وحجوزات المترجمين الحضوريين',
        'hero_eyebrow': 'للسفر والعمل',
        'hero_title': 'اطلب مترجماً حضورياً',
        'hero_desc': 'حدّد اللغات ونوع الخدمة ونقطة اللقاء، ثم أرسل طلباً فورياً أو حجزاً مجدولاً. يعتمد قبول الطلب على توفر المترجم.',
        'f2_title': 'اختيار اللغات',
        'f2_desc': 'حدّد لغتي المصدر والوجهة في طلبك.',
        'f3_title': 'تفاصيل المترجم بعد القبول',
        'f3_desc': 'تظهر تفاصيل المترجم بعد قبول طلبك.',
        'trust_verified': 'المطابقة حسب الطلب',
        'trust_verified_sub': 'حدّد اللغات ونوع الخدمة',
        'trust_nda': 'حجز مجدول',
        'trust_nda_sub': 'اختر وقتاً مستقبلياً لطلبك',
        'mobile_card_desc': 'قدّم طلباً فورياً أو حجزاً مجدولاً؛ يعتمد القبول على توفر المترجم.',
        'card_desc': 'سجّل الدخول برقم هاتفك لتقديم طلب مترجم حضوري.',
        'otp_note': 'يتطلب تسجيل الدخول عبر الهاتف رمزاً لمرة واحدة؛ تسجيل الدخول بالبريد الإلكتروني غير متاح حالياً.',
        'otp_instruction': 'أدخل الرمز المكوّن من ۶ أرقام المرتبط بالرقم أعلاه.',
        'auth_success': 'تم تسجيل الدخول بنجاح. جارٍ فتح صفحة الطلب...',
        'footer_rights': 'هم‌زبان • طلبات وحجوزات مترجم حضوري',
    },
}
FORBIDDEN = {
    'fa': ('شبکه فعال در ۳۱ استان', 'مترجمان تأییدشده', 'احراز هویت و سوءپیشینه',
           'قرارداد رسمی NDA', 'ضمانت رازداری', 'در کمتر از چند دقیقه', 'سیستم امن فعال',
           'کد ورود از طریق پیامک ارسال می‌شود', 'در حال اتصال به نقشه و انتخاب مترجم'),
    'en': ('Active network across all airports', '31 provinces', 'Verified Interpreters',
           'Vetted background & identity', 'Guaranteed Confidentiality', 'NDA Guarantee',
           'in just minutes', 'Instant and secure access', 'Secure system active',
           'Your sign-in code is sent by SMS', 'Connecting to real-time map'),
    'ar': ('شبكة نشطة في ٣١ محافظة', 'مترجمون معتمدون', 'تحقق أمني وسجل جنائي نظيف',
           'ضمان السرية', 'اتفاقية NDA ملزمة قانونياً', 'خلال دقائق معدودة',
           'النظام الآمن مفعّل', 'يُرسل رمز الدخول برسالة نصية', 'جاري التوصيل بالخريطة'),
}


async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    page = await context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    try:
        await page.goto(BASE + '/traveler/')
        for language, copy in COPY.items():
            if language != 'fa':
                await page.locator('#lang-btn').click()
                await page.locator('#opt-' + language).click()
            for key, expected in copy.items():
                await expect(page.locator(f'[data-i18n="{key}"]')).to_have_text(expected)
            await expect(page.locator('[data-i18n="network_status"]')).to_have_count(0)
            await expect(page.locator('[data-title-key="title_secure"]')).to_have_count(0)
            body = await page.locator('body').inner_text()
            for claim in FORBIDDEN[language]:
                assert claim not in body, f'unsupported landing-page claim remains in {language}: {claim}'
        assert not errors, errors
        print(f'PASS [{width}]: Persian, English, Arabic landing copy is conditional and accurate')
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
