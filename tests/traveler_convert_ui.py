# تست رابط «تبدیل به رزرو زمان‌دار»: رزرو فوری بدون مترجم → زمان قرار → وضعیت زمان‌دار.
# باید روی سروری با HZ_TIME_SCALE=0.01 اجرا شود تا سقف ۱۰ دقیقه‌ای جستجو (≈۶ ثانیه) زود برسد.
import asyncio, re, random, sys, datetime
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8082'
results = []
def check(name, ok):
    results.append(bool(ok))
    print(('  ok   ' if ok else '  FAIL ') + name)

TRAV_LOGIN = """async (phone) => {
  const H = {'Content-Type': 'application/json'};
  await fetch('/api/auth/request-code', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler'})});
  const v = await (await fetch('/api/auth/verify', {method:'POST', headers:H, body: JSON.stringify({phone, role:'traveler', code:'123456'})})).json();
  localStorage.setItem('hamzaban.token.v1', v.token);
  localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'علی', last:'رضایی', gender:'مرد', phone}));
  return v.token;
}"""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        P = await ctx.new_page(); errs = []; P.on('pageerror', lambda e: errs.append(str(e)[:120]))
        await P.goto(BASE + '/traveler/index.html'); await P.wait_for_timeout(500)
        await P.evaluate(TRAV_LOGIN, '9' + str(random.randint(100000000, 999999999)))
        await P.goto(BASE + '/traveler/app.html'); await P.wait_for_timeout(1200)
        place = 'تبدیل زمان ' + str(random.randint(100, 999))
        created = await P.evaluate("""async (place)=>{const t=localStorage.getItem('hamzaban.token.v1');
            const r=await fetch('/api/traveler/bookings',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},
              body:JSON.stringify({kind:'instant',origin_lang:'ar',dest_lang:'fa',place,traveler_name:'علی رضایی'})});
            return {status:r.status, body: await r.json()};}""", place)
        check('رزرو فوری ساخته شد', created['status'] == 201)
        bid = created['body']['id']
        # انتظار برای پایان سقف جستجو (با مقیاس زمانی تست حدود ۶ ثانیه)
        await P.wait_for_timeout(9000)
        await P.reload(); await P.wait_for_timeout(1200)
        await P.evaluate("()=>document.querySelector('nav a[data-nav=bookings]').click()")
        await P.wait_for_timeout(500)
        has_btn = await P.evaluate("()=>[...document.querySelectorAll('#bk-list button')].some(x=>x.textContent.trim()==='تبدیل به رزرو زمان‌دار')")
        check('دکمه‌ی «تبدیل به رزرو زمان‌دار» بعد از سقف جستجو ظاهر شد', has_btn)
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-list button')].find(x=>x.textContent.trim()==='تبدیل به رزرو زمان‌دار'); b && b.click();}")
        await P.wait_for_timeout(400)
        tomorrow = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        await P.fill('#bk-modal input[type=date]', tomorrow)
        await P.select_option('#bk-modal select', '10:00')
        await P.evaluate("()=>{const b=[...document.querySelectorAll('#bk-modal button')].find(x=>x.textContent.trim()==='ثبت زمان‌دار'); b && b.click();}")
        await P.wait_for_timeout(1500)
        st = await P.evaluate("""async (bid)=>{const t=localStorage.getItem('hamzaban.token.v1');
            const r=await fetch('/api/traveler/bookings',{headers:{Authorization:'Bearer '+t}});
            const d=await r.json(); return d.bookings.find(b=>b.id===bid);}""", bid)
        check('سرور رزرو را زمان‌دار و در انتظار تطبیق ثبت کرد', st and st.get('kind') == 'scheduled' and st.get('status') in ('waiting_schedule', 'matching'))
        check('خطای صفحه‌ها', not errs)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})', errs if errs else '')
        sys.exit(0 if ok else 1)

asyncio.run(main())
