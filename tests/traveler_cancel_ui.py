# تست لغو از صفحه‌ی جستجو: رزرو فوری در جستجو → دکمه‌ی لغو صفحه‌ی جستجو → سرور باید رزرو را لغو کند و پس از همگام‌سازی هم «در جستجو» برنگردد.
import asyncio, re, random, sys
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8081'
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
        place = 'لغو جستجو ' + str(random.randint(100, 999))
        created = await P.evaluate("""async (place)=>{const t=localStorage.getItem('hamzaban.token.v1');
            const r=await fetch('/api/traveler/bookings',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},
              body:JSON.stringify({kind:'instant',origin_lang:'ar',dest_lang:'fa',place,traveler_name:'علی رضایی'})});
            return {status:r.status, body: await r.json()};}""", place)
        check('رزرو فوری ساخته شد', created['status'] == 201)
        bid = created['body']['id']
        await P.wait_for_timeout(6000) # همگام‌سازی رزرو ساخته‌شده از API به فهرست محلی
        await P.evaluate("()=>document.getElementById('btn-cancel-search').click()")
        await P.wait_for_timeout(1500)
        st = await P.evaluate("""async (bid)=>{const t=localStorage.getItem('hamzaban.token.v1');
            const d=await (await fetch('/api/traveler/bookings',{headers:{Authorization:'Bearer '+t}})).json();
            return d.bookings.find(b=>b.id===bid).status;}""", bid)
        check('سرور رزرو را لغو کرد', st == 'cancelled')
        # چند همگام‌سازی بگذرد؛ وضعیت نباید به «در جستجو» برگردد
        await P.wait_for_timeout(6500)
        local = await P.evaluate("()=>JSON.parse(localStorage.getItem('hamzaban.bookings.v1')||'[]').find(x=>x.place==='%s')" % place)
        check('پس از همگام‌سازی، رزرو لغوشده می‌ماند', local and local.get('tab') == 'cancelled')
        check('خطای صفحه‌ها', not errs)
        await b.close()
        ok = all(results)
        print('RESULT:', 'PASS' if ok else 'FAIL', f'({sum(results)}/{len(results)})', errs if errs else '')
        sys.exit(0 if ok else 1)

asyncio.run(main())
