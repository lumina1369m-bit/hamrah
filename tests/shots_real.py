import asyncio, json, sys
from playwright.async_api import async_playwright
from hz_api import LOGIN_JS, SEED_JS
import random
JOBS = [
  ('tr_login', 'http://127.0.0.1:8081/translator/index.html', None),
  ('tr_desk',  'http://127.0.0.1:8081/translator/app.html', 'desk'),
  ('tr_missions', 'http://127.0.0.1:8081/translator/app.html', 'desk_missions'),
  ('tr_success', 'http://127.0.0.1:8081/translator/index.html', 'success'),
  ('tg_login', 'http://127.0.0.1:8081/traveler/index.html', None),
]
DESK_SEED = "()=>{const s=HZ.load(); s.status='active_general'; s.session={until:9999999999999}; s.profile={nameFa:'علی',lastFa:'رضایی'}; HZ.save(s)}"
MISSIONS = "()=>{const s=HZ.load(); s.status='active_general'; s.session={until:9999999999999}; s.profile={nameFa:'علی',lastFa:'رضایی'}; s.missions=[{code:'M-1001',purpose:'مذاکره تجاری',travelerName:'Christopher Reid',place:'نمایشگاه تهران',startAt:new Date(Date.now()+5*86400000).toISOString(),total:3200000,net:2560000,status:'accepted'}]; HZ.save(s)}"
MISSION_LIST = [{'code': 'M-1001', 'purpose': 'مذاکره تجاری', 'travelerName': 'Christopher Reid', 'place': 'نمایشگاه تهران', 'startAt': '2026-10-25T10:00:00', 'total': 3200000, 'net': 2560000, 'status': 'accepted'}]

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        for name, url, mode in JOBS:
            for w in (390, 1280):
                ctx = await b.new_context(viewport={'width': w, 'height': 900})
                pg = await ctx.new_page(); errs = []
                pg.on('pageerror', lambda e: errs.append(str(e)[:120]))
                await pg.goto(url.split('/app')[0] + '/index.html' if mode else url, wait_for_timeout=0) if False else None
                await pg.goto(url.replace('/app.html','/index.html') if mode else url); await pg.wait_for_timeout(1500)
                if mode:
                    token = await pg.evaluate(LOGIN_JS, '9' + str(random.randint(100000000, 999999999)))
                    if mode == 'desk_missions':
                        await pg.evaluate(SEED_JS, [token, MISSION_LIST])
                    if mode == 'success':
                        await pg.evaluate("()=>{document.querySelectorAll('.step-content').forEach(p=>p.classList.remove('active'));document.getElementById('step-panel-success').classList.add('active')}")
                    else:
                        await pg.goto(url); await pg.wait_for_timeout(1500)
                await pg.screenshot(path=f'assets/real_{name}_{w}.png', full_page=True)
                print(name, w, 'errors:', errs or 'none')
                await ctx.close()
        await b.close()
asyncio.run(main())
