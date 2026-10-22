# تست امکانات از سرور در هر سه اپ: خاموش‌کردن امکان در پنل مدیر باید بخش مربوط را در اپ‌ها پنهان یا غیرفعال کند.
import asyncio, re, json, random, sys, urllib.request
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8098'
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else 'test-admin-pass'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

def api(method, path, body=None, token=None):
    h = {'Content-Type': 'application/json'}
    if token: h['Authorization'] = 'Bearer ' + token
    rq = urllib.request.Request(BASE + '/api' + path, method=method, headers=h,
                                data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(rq, timeout=10) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')

TRAV_LOGIN = """async (phone) => {
  const H = {'Content-Type': 'application/json'};
  await fetch('/api/auth/request-code', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler'})});
  const v = await (await fetch('/api/auth/verify', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler', code:'123456'})})).json();
  localStorage.setItem('hamzaban.token.v1', v.token);
  localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'علی', last:'رضایی', gender:'مرد', phone}));
  return v.token;
}"""
TR_LOGIN = """async ([phone, token]) => {
  const st = HZ.load(); st.token = token; st.session = {phone, until: Date.now() + 3600e3};
  for (let i = 0; i < 8; i++) st.completed[i] = true; st.status = 'active_general'; st.profile = {nameFa: 'نازنین', lastFa: 'تست'}; HZ.save(st); return true;
}"""

def disp(page, sel):
    return page.evaluate("(s)=>{const e=document.querySelector(s); return e ? getComputedStyle(e).display : 'missing'}", sel)

async def main():
    _, adm = api('POST', '/admin/login', {'password': PASSWORD})
    atok = adm['token']
    off = {'booking_convert': False, 'expiry_notifications': False, 'instant_booking': False, 'car_mode': False, 'translator_online': False,
           'interview_scheduling': False, 'translator_registration': False}
    s, r = api('PUT', '/admin/features', off, atok)
    check('خاموش‌کردن امکان‌ها از API پذیرفته شد', s == 200)
    s, r = api('POST', '/traveler/bookings', None, None)  # بدون نشست: باید رد شود (احراز هویت)
    check('بدون نشست، رزرو پذیرفته نمی‌شود', s == 401)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        # ورود مسافر
        await pg.goto(BASE + '/traveler/index.html'); await pg.wait_for_timeout(900)
        check('زبانهٔ ایمیل ورود پنهان است', await disp(pg, '#tab-email') == 'none')
        phone = '9' + str(random.randint(100000000, 999999999))
        await pg.evaluate(TRAV_LOGIN, phone)
        await pg.goto(BASE + '/traveler/app.html'); await pg.wait_for_timeout(1500)
        check('دکمه‌ی حالت فوری پنهان است', await disp(pg, '#btn-mode-instant') == 'none')
        check('دکمه‌ی زمان‌دار نمایش داده می‌شود', await disp(pg, '#btn-mode-scheduled') != 'none')
        check('انتخاب خودرو پنهان است', await disp(pg, '#btn-toggle-car') == 'none')
        check('ثبت رزرو نشان داده شده ولی فعال است', await pg.evaluate("()=>!document.getElementById('btn-main-submit').disabled"))
        # مترجم: ثبت‌نام و آنلاین
        await pg.goto(BASE + '/translator/index.html'); await pg.wait_for_timeout(900)
        note = await pg.evaluate("()=>document.body.innerText.includes('ثبت‌نام مترجمان فعلاً بسته است')")
        check('پیام بسته‌بودن ثبت‌نام مترجم نمایش داده می‌شود', note)
        cities_ui = await pg.evaluate("()=>[...document.querySelectorAll('#cityList button')].map(b=>b.textContent.trim())")
        cities_api = api('GET', '/config')[1].get('translator_cities', [])
        check('چیپ‌های شهر مترجم از سرور ساخته شده‌اند', len(cities_ui) == len(cities_api) and len(cities_api) > 0 and all(c['name_fa'] in cities_ui for c in cities_api))
        check('دکمه‌های ثبت‌نام غیرفعال‌اند', await pg.evaluate(
            "()=>{const bs=[...document.querySelectorAll('[onclick*=\"finishRegistration\"]')]; return bs.length===0 || bs.every(x=>x.disabled)}"))
        tphone = '9' + str(random.randint(100000000, 999999999))
        await pg.goto(BASE + '/translator/index.html'); await pg.wait_for_timeout(500)
        await pg.evaluate(TR_LOGIN, [tphone, 'x'])  # حالت ساده برای بارگذاری میز کار
        await pg.goto(BASE + '/translator/app.html'); await pg.wait_for_timeout(1500)
        check('کارت مصاحبه در میز کار پنهان است', await disp(pg, '#iv-box') == 'none')
        check('کلید آنلاین پنهان است', await disp(pg, '[aria-label="تغییر وضعیت آماده به خدمت"]') == 'none')
        check('خطای صفحه‌ها', not errs)
        # سمت سرور: رزرو فوری خاموش باید رد شود
        tok = await pg.evaluate("()=>localStorage.getItem('hamzaban.token.v1')")
        s, r = api('POST', '/traveler/bookings', {'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa', 'place': 'تست', 'traveler_name': 'x'}, tok) if tok else (0, {})
        check('سرور رزرو فوری خاموش را رد می‌کند', s == 409 and r.get('error') == 'feature_disabled')
        await b.close()
    # بازگردانی
    on = {k: True for k in off}
    api('PUT', '/admin/features', on, atok)
    failed = results.count(False)
    print(f'نتیجه: {results.count(True)} موفق، {failed} ناموفق')
    sys.exit(1 if failed else 0)

asyncio.run(main())
