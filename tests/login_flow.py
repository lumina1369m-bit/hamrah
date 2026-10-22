import random
RANDPHONE = '9' + str(random.randint(100000000, 999999999))  # شماره‌ی تازه برای هر اجرا (محدودیت ارسال مجدد)
import asyncio, re, json, sys
from playwright.async_api import async_playwright
lang = sys.argv[1]
ANY = re.compile(r'[\u0600-\u06FF]'); PF = re.compile(r'[پچژگک۰-۹]')
DIG = re.compile(r'^[\s\d۰-۹٠-٩.,:٫٬/%٪\-+()~$]*$')
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        await ctx.route(re.compile(r'https://(unpkg\.com|fonts\.googleapis\.com|fonts\.gstatic\.com).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs=[]
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto('http://127.0.0.1:8081/traveler/index.html'); await pg.wait_for_timeout(800)
        await pg.evaluate("l=>{localStorage.setItem('hamzaban_lang',l); location.reload()}", lang)
        await pg.wait_for_timeout(1000)
        left = {}
        async def scan(step):
            texts = await pg.evaluate("""()=>{const o=[];const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;
              while(n=w.nextNode()){const t=n.nodeValue.trim(); if(!t) continue; const el=n.parentElement;
              if(!el||el.closest('script,style,option')||!el.getClientRects().length) continue; if(getComputedStyle(el).visibility==='hidden') continue; o.push(t)}
              document.querySelectorAll('input').forEach(i=>{ if(i.placeholder&&i.getClientRects().length) o.push(i.placeholder)});
              document.querySelectorAll('[title],[aria-label]').forEach(i=>{ if(i.getClientRects().length){ if(i.title) o.push(i.title); if(i.getAttribute('aria-label')) o.push(i.getAttribute('aria-label'))}});
              return o;}""")
            for t in texts:
                if DIG.match(t) or len(t)<2: continue
                if (lang=='en' and ANY.search(t)) or (lang=='ar' and PF.search(t)): left.setdefault(t, step)
        async def toast_or_alert():
            return await pg.evaluate("()=>{const a=document.getElementById('auth-alert');const e=document.getElementById('ident-err');const o=document.getElementById('otp-err');return [a&&!a.classList.contains('hidden')?a.textContent.trim():'',e&&!e.classList.contains('hidden')?e.textContent.trim():'',o&&!o.classList.contains('hidden')?o.textContent.trim():''].filter(Boolean).join(' | ')}")
        res=[]
        await scan('login-start')
        # step 1: send code without consents
        res.append(('send disabled without consents', await pg.is_disabled('#btn-request-otp'))); await scan('err-no-consent')
        # phone invalid
        await pg.fill('#phone-input', '12'); await pg.check('#check-age'); await pg.check('#check-terms')
        res.append(('invalid phone disabled', await pg.is_disabled('#btn-request-otp')))
        await pg.fill('#phone-input', RANDPHONE)
        await pg.click('#btn-request-otp', timeout=2000); await pg.wait_for_timeout(600)
        res.append(('step after send', await pg.evaluate("()=>[...document.querySelectorAll('#step-identity,#step-otp,#step-identifier')].map(e=>e.id+':'+(e.classList.contains('hidden')?'hidden':'shown')).join(' ')")))
        await scan('otp-step')
        # wrong code then demo fill
        res.append(('verify disabled when empty', await pg.is_disabled('#btn-verify'))); await scan('otp-err')
        await pg.click('button[onclick="fillTestCode()"]', timeout=2000); await pg.wait_for_timeout(300)
        res.append(('after demo fill', await pg.evaluate("()=>[...document.querySelectorAll('#otp-inputs-wrapper input')].map(i=>i.value).join('')")))
        await pg.wait_for_timeout(600)
        if await pg.is_visible('#btn-verify'):
            await pg.click('#btn-verify', timeout=2000); await pg.wait_for_timeout(900)
        res.append(('after verify step', await pg.evaluate("()=>['step-identity','step-otp','step-identifier'].map(i=>i+':'+(document.getElementById(i).classList.contains('hidden')?'hidden':'shown')).join(' ')")))
        if await pg.is_visible('#step-identity'):
            await scan('identity-step')
            res.append(('save disabled empty', await pg.is_disabled('#id-save')))
            await pg.fill('#id-name', 'Ali'); await pg.fill('#id-last', 'Rezaei')
            await pg.locator('.id-gender').nth(1).click(); await pg.wait_for_timeout(200)
            await scan('identity-filled')
            await pg.click('#id-save', timeout=2000); await pg.wait_for_timeout(1500)
        res.append(('after verify url', pg.url.split('/')[-1]))
        await pg.wait_for_timeout(800)
        res.append(('app dir/lang', await pg.evaluate("()=>document.documentElement.dir+' '+(localStorage.getItem('hamzaban_lang')||'-')")))
        print('== %s' % lang)
        for k,v in res: print('  %-28s %s' % (k, v))
        print('  errors:', errs or 'none')
        print('  left:', len(left))
        for k,v in left.items(): print('    [%s] %s' % (v,k[:110]))
        await b.close()
asyncio.run(main())
