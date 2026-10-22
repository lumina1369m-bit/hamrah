# بررسی انتشار: دکمه‌ی «تأیید کارشناس (آزمایشی)» نباید در رابط کاربری باشد؛ تأیید فقط از مسیر سرور/کارشناس انجام می‌شود.
# این ابزار تشخیصی پس از ورود از طریق API بررسی می‌کند دکمه وجود ندارد و ورود به میز کار با تأیید سرور انجام می‌شود.
import asyncio, re, random
from playwright.async_api import async_playwright
async def m():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox']); ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)[:120]))
        await pg.goto('http://127.0.0.1:8081/translator/index.html'); await pg.wait_for_timeout(900)
        phone = '9' + str(random.randint(100000000, 999999999))
        await pg.evaluate("""async (phone)=>{const H={'Content-Type':'application/json'};
            await fetch('/api/auth/request-code',{method:'POST',headers:H,body:JSON.stringify({phone,role:'translator'})});
            const v=await (await fetch('/api/auth/verify',{method:'POST',headers:H,body:JSON.stringify({phone,role:'translator',code:'123456'})})).json();
            const st=HZ.load(); st.token=v.token; st.session={phone,until:Date.now()+3600e3}; st.completed[1]=true; st.status='pending_review'; HZ.save(st);}""", phone)
        await pg.reload(); await pg.wait_for_timeout(900)
        await pg.evaluate("()=>{document.querySelectorAll('.step-content').forEach(p=>p.classList.remove('active'));document.getElementById('step-panel-success').classList.add('active')}")
        await pg.wait_for_timeout(300)
        print('test-approve button absent (expected):', await pg.evaluate("()=>!document.getElementById('test-approve-btn')"))
        await pg.evaluate("""async()=>{const t=HZ.load().token; await fetch('/api/dev/approve-translator',{method:'POST',headers:{Authorization:'Bearer '+t}}); enterDesk();}""")
        await pg.wait_for_timeout(1500)
        print('desk url:', pg.url.split('/')[-1], '| errs:', [e for e in errs if 'tailwind' not in e] or 'none')
        await b.close()
asyncio.run(m())
