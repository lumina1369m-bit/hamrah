# تست یکپارچه‌ی دو اپ: مسافر رزرو می‌سازد، مترجم پیشنهاد را می‌بیند و می‌پذیرد، و وضعیت به اپ مسافر برمی‌گردد.
import asyncio, re, json, random
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS

BASE = 'http://127.0.0.1:8081'
import urllib.request
urllib.request.urlopen(urllib.request.Request(BASE + '/api/dev/offline-all', method='POST'), timeout=10).read()  # فقط توسعه: پاک‌سازی مترجمان و رزروهای باز قبلی
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
        route = lambda ctx: ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        # ---- مترجم: فعال و آنلاین ----
        tctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(tctx)
        T = await tctx.new_page(); terr = []; T.on('pageerror', lambda e: terr.append(str(e)[:120]))
        await T.goto(BASE + '/translator/index.html'); await T.wait_for_timeout(600)
        tphone = '9' + str(random.randint(100000000, 999999999))
        await T.evaluate(LOGIN_JS, tphone)
        await T.evaluate("async()=>{const t=HZ.load().token; await fetch('/api/translator/online',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},body:JSON.stringify({online:true})});}")
        # ---- مسافر: ورود و رزرو فوری ----
        pctx = await b.new_context(viewport={'width': 390, 'height': 900}); await route(pctx)
        P = await pctx.new_page(); perr = []; P.on('pageerror', lambda e: perr.append(str(e)[:120]))
        await P.goto(BASE + '/traveler/index.html'); await P.wait_for_timeout(500)
        await P.evaluate(TRAV_LOGIN, '9' + str(random.randint(100000000, 999999999)))
        await P.goto(BASE + '/traveler/app.html'); await P.wait_for_timeout(1200)
        place = 'تست همگام‌سازی ' + str(random.randint(100, 999))
        created = await P.evaluate("""async (place)=>{const t=localStorage.getItem('hamzaban.token.v1');
            const r=await fetch('/api/traveler/bookings',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+t},
              body:JSON.stringify({kind:'instant',origin_lang:'ar',dest_lang:'fa',place,traveler_name:'علی رضایی'})});
            return {status:r.status, body: await r.json()};}""", place)
        print('booking created:', created['status'], created['body'].get('status'))
        # ---- مترجم: پیشنهاد را می‌بیند و می‌پذیرد ----
        await T.goto(BASE + '/translator/app.html'); await T.wait_for_timeout(4500)
        offer_text = await T.evaluate("()=>document.getElementById('offers-box').textContent")
        print('translator sees offer:', place in offer_text)
        await T.evaluate("""()=>{const box=document.getElementById('offers-box'); const btn=[...box.querySelectorAll('button')].find(b=>b.textContent.trim()==='پذیرش'); btn && btn.click();}""")
        await T.wait_for_timeout(1500)
        missions = await T.evaluate("()=>document.getElementById('missions-list').textContent")
        print('translator mission listed:', place in missions)
        # ---- مسافر: وضعیت باید همگام شود ----
        await P.wait_for_timeout(6500)
        bk = await P.evaluate("()=>JSON.parse(localStorage.getItem('hamzaban.bookings.v1')||'[]')")
        mine = [x for x in bk if x.get('place') == place]
        print('traveler local status:', mine[0].get('statusLabel') if mine else 'missing', '| tab:', mine[0].get('tab') if mine else '-')
        dbg = await P.evaluate("async()=>{const t=localStorage.getItem('hamzaban.token.v1'); const r=await fetch('/api/traveler/bookings',{headers:{Authorization:'Bearer '+t}}); return {api:(await r.json()).bookings.map(b=>b.status), tokenLen:(t||'').length, local: JSON.parse(localStorage.getItem('hamzaban.bookings.v1')||'[]').map(x=>[x.serverId,x.srvStatus,x.statusLabel])};}")
        print('debug:', json.dumps(dbg, ensure_ascii=False))
        ok = bool(mine) and mine[0].get('statusLabel') == 'مترجم تطبیق یافت'
        print('RESULT:', 'PASS' if ok and place in offer_text else 'FAIL', '| errors:', [e for e in terr + perr if 'tailwind' not in e] or 'none')
        await b.close()
        raise SystemExit(0 if (ok and place in offer_text) else 1)
asyncio.run(main())
