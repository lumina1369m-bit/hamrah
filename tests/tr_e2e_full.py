import asyncio, re, json, sys, random
from playwright.async_api import async_playwright
W = int(sys.argv[1]) if len(sys.argv) > 1 else 390
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': W, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []; log = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
        await pg.goto('http://127.0.0.1:8081/translator/index.html'); await pg.wait_for_timeout(700)
        # 1. login
        await pg.fill('#mobileInput', '9' + str(random.randint(100000000, 999999999))); await pg.check('#c-age'); await pg.check('#c-terms')
        await pg.click('#sendOtpBtn'); await pg.wait_for_timeout(400)
        boxes = pg.locator('#step-panel-1 input[type=text]')
        for i, d in enumerate('123456'): await boxes.nth(i).fill(d)
        await pg.wait_for_timeout(800)
        log.append(('after code', await pg.evaluate("()=>document.getElementById('step-panel-2').offsetHeight>0")))
        # 2..5: click the visible forward button of each panel
        for step in (3, 4, 5):
            ok = await pg.evaluate("""(n)=>{const panel=document.getElementById('step-panel-'+(n-1));
               const btn=[...panel.querySelectorAll('button')].find(b=>(b.getAttribute('onclick')||'').includes('goToStep('+n+')')&&b.offsetHeight);
               if(!btn) return false; btn.click(); return true;}""", step)
            log.append((f'go to step {step}', ok))
            await pg.wait_for_timeout(300)
        # step 5 -> finish
        ok = await pg.evaluate("""()=>{const b=[...document.querySelectorAll('button')].find(b=>(b.getAttribute('onclick')||'').includes('finishRegistration()')&&b.offsetHeight);
           if(!b) return false; b.click(); return true;}""")
        log.append(('finish clicked', ok)); await pg.wait_for_timeout(700)
        log.append(('success panel', await pg.evaluate("()=>document.getElementById('step-panel-success').classList.contains('active')")))
        log.append(('status after finish', await pg.evaluate("()=>HZ.load().status")))
        # enter desk before approval: must show message, stay on index
        log.append(('success visible', await pg.evaluate("()=>document.getElementById('step-panel-success').offsetHeight>0")))
        log.append(('panels', await pg.evaluate("()=>[1,2,3,4,5,'success'].map(n=>n+':'+(document.getElementById('step-panel-'+n).offsetHeight>0?'v':'h')).join(' ')")))
        if not any(k=='success visible' and v for k,v in log):
            for k,v in log: print(f'  {k:28s} {v}')
            print('  errors:', errs[:5]); await b.close(); return
        await pg.evaluate("()=>document.querySelector('#step-panel-success button[onclick=\"enterDesk()\"]').click()"); await pg.wait_for_timeout(300)
        log.append(('pending message', (await pg.text_content('#desk-msg') or '')[:30]))
        log.append(('still index before approval', pg.url.split('/')[-1] == 'index.html'))
        srv = await pg.evaluate("async()=>{const t=HZ.load().token; const r=await fetch('/api/translator/status',{headers:{Authorization:'Bearer '+t}}); return (await r.json()).status;}")
        log.append(('server status before approval', srv))
        assert srv == 'pending_review', f'server status {srv}'
        # 3. test approval -> desk
        await pg.click('#test-approve-btn'); await pg.wait_for_timeout(1500)
        log.append(('desk url', pg.url.split('/')[-1]))
        # 4. desk checks
        d = await pg.evaluate("""()=>({h: document.querySelector('h1,h2') && document.querySelector('h2').textContent.trim(),
            missions: [...document.getElementById('missions-list').children].map(c=>c.textContent.trim().slice(0,30)),
            schedule: document.getElementById('schedule-list').children.length,
            sampleHidden: document.getElementById('missions-sample').classList.contains('hidden'),
            hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth})""")
        log.append(('desk info', d))
        print(f'== full e2e {W}px')
        for k, v in log: print(f'  {k:28s} {v}')
        print('  errors:', [e for e in errs if 'tailwind' not in e] or 'none')
        await pg.screenshot(path=f'assets/tr_e2e_desk_{W}.png')
        await b.close()
asyncio.run(main())
