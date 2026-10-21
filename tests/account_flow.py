import asyncio, re, json, sys
from playwright.async_api import async_playwright
lang = sys.argv[1]
ANY = re.compile(r'[\u0600-\u06FF]'); PF = re.compile(r'[پچژگک۰-۹]')
DIG = re.compile(r'^[\s\d۰-۹٠-٩.,:٫٬/%٪\-+()~$]*$')
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        await ctx.route(re.compile(r'https://(unpkg\.com|fonts\.googleapis\.com|fonts\.gstatic\.com|nominatim\.openstreetmap\.org|tile\.openstreetmap\.org).*'), lambda r: r.abort())
        await ctx.add_init_script("if(!sessionStorage.getItem('s')){localStorage.setItem('hamzaban.user.v1',JSON.stringify({name:'علی',last:'رضایی',gender:'male',verified:false,phone:'+989121234567'}));localStorage.setItem('hamzaban_lang','%s');sessionStorage.setItem('s','1')}" % lang)
        pg = await ctx.new_page(); errs=[]
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto('http://127.0.0.1:8081/traveler/app.html'); await pg.wait_for_timeout(1200)
        left = {}
        async def scan(step):
            texts = await pg.evaluate("""()=>{const o=[];const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;
              while(n=w.nextNode()){const t=n.nodeValue.trim(); if(!t) continue; const el=n.parentElement;
              if(!el||el.closest('script,style')||!el.getClientRects().length) continue; if(getComputedStyle(el).visibility==='hidden') continue; o.push(t)} 
              document.querySelectorAll('input,textarea').forEach(i=>{ if(i.placeholder&&i.getClientRects().length) o.push(i.placeholder)});
              return o;}""")
            for t in texts:
                if DIG.match(t) or len(t)<2: continue
                if (lang=='en' and ANY.search(t)) or (lang=='ar' and PF.search(t)):
                    left.setdefault(t, step)
        async def toast():
            return await pg.evaluate("()=>{const p=document.getElementById('toast-pill');return p&&!p.classList.contains('hidden')?document.getElementById('toast-text').textContent:null}")
        async def hide_toast():
            await pg.evaluate("()=>{const t=document.getElementById('toast-pill');if(t)t.classList.add('hidden');}")
        res = []
        await pg.click('[data-nav="account"]', timeout=3000); await pg.wait_for_timeout(500)
        await scan('account')
        await pg.fill('#ac-name', ''); await pg.click('#ac-save', timeout=2000); await pg.wait_for_timeout(300)
        res.append(('save empty name', await toast())); await hide_toast()
        await pg.fill('#ac-name', 'علی'); await pg.click('#ac-save', timeout=2000); await pg.wait_for_timeout(300)
        res.append(('save ok', await toast())); await hide_toast()
        await pg.click('#ac-gender-btn', timeout=2000); await pg.wait_for_timeout(300)
        res.append(('gender change', await toast())); await hide_toast(); await scan('after-gender')
        await pg.click('#ac-contact-btn', timeout=2000); await pg.wait_for_timeout(300)
        res.append(('contact change', await toast())); await hide_toast()
        # delete flow
        await pg.click('#ac-delete', timeout=2000); await pg.wait_for_timeout(300)
        await scan('delete-box')
        await pg.fill('#ac-delete-input', 'wrong'); dis1 = await pg.is_disabled('#ac-delete-confirm')
        word = {'fa':'حذف حساب','en':'Delete account','ar':'حذف الحساب'}[lang]
        await pg.fill('#ac-delete-input', word); dis2 = await pg.is_disabled('#ac-delete-confirm')
        res.append(('delete confirm enabled for word=%s' % word, 'wrong disabled=%s, correct disabled=%s' % (dis1, dis2)))
        await pg.fill('#ac-delete-input', '')
        # language switch from profile
        await pg.select_option('#hz-lang-select', 'fa' if lang!='fa' else 'en'); await pg.wait_for_timeout(300)
        res.append(('switch to other lang dir', await pg.evaluate("()=>document.documentElement.dir+' '+localStorage.getItem('hamzaban_lang')")))
        await pg.select_option('#hz-lang-select', lang); await pg.wait_for_timeout(300)
        await scan('after-lang-switch')
        res.append(('back to', await pg.evaluate("()=>document.documentElement.dir+' '+localStorage.getItem('hamzaban_lang')")))
        print('== %s' % lang)
        for k,v in res: print('  %-40s %s' % (k, v))
        print('  errors:', errs or 'none')
        print('  left:', len(left))
        for k,v in left.items(): print('    [%s] %s' % (v,k[:110]))
        await b.close()
asyncio.run(main())
