import asyncio, re, json, sys, time
from playwright.async_api import async_playwright
PORT = 8081
PERSIAN_ONLY = re.compile(r'[پچژگک۰-۹]')
ANY_FA = re.compile(r'[\u0600-\u06FF]')
DIG = re.compile(r'^[\s\d۰-۹٠-٩.,:٫٬/%٪\-+()~$]*$')
def seed():
    now = int(time.time()*1000)
    return [
     {'id':'b1','tab':'pending','title':'عربی ← فارسی','when':'امروز ۱۴:۰۰','field':'عمومی','hours':'۲ ساعت','amount':'۲٬۴۰۰٬۰۰۰ تومان','rate':1200000,'hoursNum':2,'car':False,'pax':1,'startAt':now+3*3600e3,'base':2000000,'tax':400000,'total':2400000,'statusLabel':'در انتظار تطبیق','mode':'scheduled','retried':True},
     {'id':'b2','tab':'pending','title':'فارسی ← عربی','when':'فوری','field':'پزشکی','hours':'۱ ساعت','amount':'۱٬۲۰۰٬۰۰۰ تومان','rate':1200000,'hoursNum':1,'car':True,'pax':2,'startAt':now+10*60e3,'base':1000000,'tax':200000,'total':1200000,'statusLabel':'در انتظار تطبیق','mode':'scheduled'},
     {'id':'b3','tab':'upcoming','title':'عربی ← فارسی','when':'فردا ۰۹:۰۰','field':'عمومی','hours':'۳ ساعت','amount':'۳٬۶۰۰٬۰۰۰ تومان','rate':1200000,'hoursNum':3,'car':False,'pax':1,'startAt':now+30*3600e3,'base':3000000,'tax':600000,'total':3600000,'statusLabel':'پیش رو','mode':'scheduled'},
     {'id':'b4','tab':'done','title':'عربی ← فارسی','when':'دیروز','field':'عمومی','hours':'۲ ساعت','amount':'۲٬۴۰۰٬۰۰۰ تومان','rate':1200000,'hoursNum':2,'car':False,'pax':1,'startAt':now-30*3600e3,'base':2000000,'tax':400000,'total':2400000,'statusLabel':'انجام‌شده','mode':'scheduled'},
     {'id':'b5','tab':'cancelled','title':'فارسی ← عربی','when':'فوری','field':'عمومی','hours':'۱ ساعت','amount':'۱٬۲۰۰٬۰۰۰ تومان','rate':1200000,'hoursNum':1,'car':False,'pax':1,'statusLabel':'لغوشده','mode':'instant'},
    ]
async def main(lang):
    out = {'lang': lang, 'errors': [], 'left': {}, 'steps': {}}
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        await ctx.route(re.compile(r'https://(unpkg\.com|fonts\.googleapis\.com|fonts\.gstatic\.com).*'), lambda r: r.abort())
        await ctx.add_init_script("""try{ if(!sessionStorage.getItem('seeded')){
          localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'Test',verified:false}));
          localStorage.setItem('hamzaban.bookings.v1', %s);
          localStorage.setItem('hamzaban_lang','%s'); sessionStorage.setItem('seeded','1'); } }catch(e){}""" % (json.dumps(json.dumps(seed(), ensure_ascii=False)), lang))
        pg = await ctx.new_page()
        pg.on('pageerror', lambda e: out['errors'].append(str(e)[:150]))
        await pg.goto('http://127.0.0.1:%d/traveler/app.html' % PORT); await pg.wait_for_timeout(1500)
        async def collect(step):
            texts = await pg.evaluate("""()=>{const o=[];const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;
              while(n=w.nextNode()){const t=n.nodeValue.trim(); if(!t) continue; const el=n.parentElement;
              if(!el||el.closest('script,style')) continue; if(!el.getClientRects().length) continue; const cs=getComputedStyle(el); if(cs.visibility==='hidden') continue; o.push(t)} return o;}""")
            bad = []
            for t in texts:
                if DIG.match(t) or len(t) < 2: continue
                if lang == 'en' and ANY_FA.search(t): bad.append(t)
                if lang == 'ar' and PERSIAN_ONLY.search(t): bad.append(t)
            out['steps'].setdefault(step, [])
            out['steps'][step] = sorted(set(out['steps'][step] + [t for t in texts if len(t) < 90][:60]))[:80]
            for t in bad: out['left'].setdefault(t, step)
        async def click_text(sel_text, step, container=None):
            loc = pg.locator('button', has_text=re.compile('^\\s*%s\\s*$' % re.escape(sel_text))).locator('visible=true')
            n = await loc.count()
            if n == 0:
                out['left']['__missing_button:' + sel_text] = step; return False
            await loc.last.click(timeout=3000); await pg.wait_for_timeout(400); return True
        await pg.click('[data-nav="bookings"]', timeout=3000); await pg.wait_for_timeout(600)
        tabs = pg.locator('#bk-tabs button')
        async def tab(i, step):
            await tabs.nth(i).click(); await pg.wait_for_timeout(300); await collect(step)
        await tab(0, 'tab-pending')
        await collect('bookings-pending')
        card = lambda i: pg.locator('#bk-list > article').nth(i)
        async def act(card_i, btn_i, step, scope='.b-act'):
            await card(card_i).locator(scope + ' button').nth(btn_i).click(timeout=3000); await pg.wait_for_timeout(400); await collect(step)
        async def modal_btn(i, step):
            await pg.locator('#bk-modal .flex.gap-2.pt-1 > button').nth(i).click(timeout=3000); await pg.wait_for_timeout(400); await collect(step)
        # retry banner on second card (b2)
        await collect('retry-banner')
        await card(1).locator('.bg-amber-50 button').nth(0).click(); await pg.wait_for_timeout(400); await collect('after-retry-toast')
        # edit modal on first card
        await act(0, 0, 'edit-modal')
        await modal_btn(0, 'edit-modal-close')
        # cancel modal on first card, keep
        await act(0, 1, 'cancel-modal')
        await modal_btn(0, 'cancel-modal-close')
        await act(0, 1, 'cancel-modal2')
        await modal_btn(1, 'cancel-confirm'); await collect('after-cancel-toast')
        for i in range(1, 5):
            await tab(i, 'tab-%d' % i)
        await tab(3, 'tab-done')
        await act(0, 0, 'invoice-modal')
        await modal_btn(0, 'invoice-close')
        await pg.screenshot(path='assets/bk_%s.png' % lang, full_page=False)
        print(lang, 'errors:', out['errors'] or 'none')
        print(lang, 'left:', len(out['left']))
        for k, v in out['left'].items(): print('  [%s] %s' % (v, k[:120]))
        json.dump(out, open('assets/bk_flow_%s.json' % lang, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        await b.close()
asyncio.run(main(sys.argv[1]))
