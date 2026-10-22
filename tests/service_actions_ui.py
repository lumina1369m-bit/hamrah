"""Service controls must use the pinned, freshly read server booking.

Faults must not create a local clock/invoice/extension. Real extension approval
and two-sided finish rules stay intact, including the full early-finish price.
"""
import asyncio
from pathlib import Path
import secrets
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking
from booking_options_ui import translator
from logout_sessions_ui import sign_in, seeded_context

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_service_actions'
ERROR = {
    'fa': 'عملیات خدمت تأیید نشد. وضعیت را بررسی کنید و دوباره تلاش کنید.',
    'en': 'The service action was not confirmed. Check its status and try again.',
    'ar': 'لم يتم تأكيد إجراء الخدمة. تحقّق من حالتها وحاول مجدداً.',
}
NOT_STARTED = {
    'fa': 'خدمت هنوز با کد امنیتی در سرور شروع نشده است.',
    'en': 'The service has not started with the security code on the server yet.',
    'ar': 'لم تبدأ الخدمة برمز الأمان على الخادم بعد.',
}
REQUIRED = {
    'fa': 'برای این کار، ورود و رزرو معتبر سروری لازم است.',
    'en': 'This action requires sign-in and a valid server booking.',
    'ar': 'يتطلب هذا الإجراء تسجيل الدخول وحجزاً صالحاً على الخادم.',
}


async def scenario(browser, lang):
    setup = await browser.new_context()
    ctx, page = None, None
    release = asyncio.Event()
    errors, posts = [], []
    try:
        await api(setup.request, 'POST', '/dev/offline-all')
        session = await sign_in(setup.request, '9' + str(secrets.randbelow(900000000) + 100000000))
        token = session['token']
        ctx, page = await seeded_context(browser, session, lang, errors)
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and '/api/traveler/bookings/' in r.url else None)
        # No server booking: synthetic service buttons cannot simulate any stage.
        before_hours = await page.locator('#label-hours-count').inner_text()
        await page.evaluate("localStorage.removeItem('hamzaban.token.v1')")
        for id in ['btn-arrived','btn-confirm-start','btn-finish-service','btn-extend-one-hour','btn-approve-finish','btn-reject-finish']:
            await page.locator('#'+id).dispatch_event('click')
            await expect(page.locator('#toast-text')).to_have_text(REQUIRED[lang])
        assert not posts
        await expect(page.locator('#stage-5')).to_be_hidden()
        await expect(page.locator('#stage-6')).to_be_hidden()
        assert await page.locator('#label-hours-count').inner_text() == before_hours
        await page.evaluate("t => localStorage.setItem('hamzaban.token.v1',t)", token)

        # Put a different, canceled server reservation first in the local list.
        old = await api(setup.request,'POST','/traveler/bookings',token,
                        {'kind':'instant','origin_lang':'ar','dest_lang':'fa','place':'old-canceled'},status=201)
        await api(setup.request,'POST',f"/traveler/bookings/{old['id']}/cancel",token)
        ttok = await translator(setup.request,'male')
        await page.reload()
        await page.wait_for_function('() => window.hzBookingsSynced === true && !!window.HZ_NEAREST_CITY()')
        await expect(page.locator('#selected-location-title')).to_have_text('تهران، آزمون خروج')
        await page.locator('#confirm-location-btn').click()
        await page.locator('#btn-toggle-car').click()
        async with page.expect_response(lambda r: r.url.endswith('/api/traveler/bookings') and r.request.method == 'POST') as pending:
            await page.locator('#btn-main-submit').click()
        created = await (await pending.value).json()
        bid, total, hours = created['id'], created['total'], created['hours']
        offers = await api(setup.request,'GET','/translator/offers',ttok)
        await api(setup.request,'POST',f"/translator/offers/{offers['offers'][0]['id']}/accept",ttok)
        await expect(page.locator('#stage-3')).to_be_visible()
        await page.evaluate("id => {let b=JSON.parse(localStorage.getItem('hamzaban.bookings.v1'));b.sort((a,c)=>(a.serverId===id?-1:c.serverId===id?1:0));localStorage.setItem('hamzaban.bookings.v1',JSON.stringify(b));}",old['id'])

        async def faults(action, button, method='POST'):
            url = '**/api/traveler/bookings' + (f'/{bid}/{action}' if method == 'POST' else '')
            modes = ['offline','503','empty','false','string','malformed','partial']
            if method == 'POST': modes.append('misleading_success')
            else: modes.extend(['bad_start_snapshot','bad_finish_snapshot'])
            for mode in modes:
                async def failure(route, request, *, mode=mode):
                    if request.method != method:
                        await route.fallback()
                    elif mode == 'offline':
                        await route.abort('failed')
                    elif mode in ['bad_start_snapshot','bad_finish_snapshot']:
                        response = await route.fetch()
                        snapshot = await response.json()
                        row = next(x for x in snapshot['bookings'] if x['id']==bid)
                        row['service_started']=True
                        if mode == 'bad_start_snapshot': row['service_started_at']='invalid'
                        else:
                            row['status']='finished'; row['finished_at']=None; row['service_started_at']='2026-01-01T00:00:00Z'
                        await route.fulfill(json=snapshot)
                    elif mode == 'misleading_success':
                        if action == 'extend':
                            payload={'pending':True,'id':999999,'extra_hours':1,'extra_total':100,'new_total':total+100,'expires_at':'2099-01-01T00:00:00Z'}
                        elif action == 'finish-reject':
                            payload={'ok':True,'status':'matched'}
                        else:
                            payload={'ok':True,'status':'finished','finished_by':'traveler' if action=='finish' else 'translator','total':total}
                        await route.fulfill(status=200,json=payload)
                    elif mode == 'malformed':
                        await route.fulfill(status=200,content_type='application/json',body='{')
                    else:
                        payload = {'503':{'error':'unavailable'},'empty':{},'false':{'ok':False},'string':{'ok':'true'},'partial':{'ok':True,'pending':True,'id':1}}[mode]
                        await route.fulfill(status=503 if mode=='503' else 200,json=payload)
                await page.route(url,failure)
                await button.dispatch_event('click')
                await expect(button).to_be_enabled()
                await expect(page.locator('#toast-text')).to_have_text(ERROR[lang])
                await page.unroute(url,failure)

        # Read failures cannot show a code or start a timer.
        await faults('arrived',page.locator('#btn-arrived'),method='GET')
        await expect(page.locator('#stage-4')).to_be_hidden()
        await page.locator('#btn-arrived').click()
        await expect(page.locator('#stage-4')).to_be_visible()
        code = (await page.locator('#security-code').inner_text()).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹','0123456789'))
        assert code == created['service_code'], (code,created)
        count = len(posts)
        await page.locator('#btn-confirm-start').click()
        await expect(page.locator('#toast-text')).to_have_text(NOT_STARTED[lang])
        await expect(page.locator('#stage-5')).to_be_hidden()
        assert len(posts) == count
        await api(setup.request,'POST',f'/translator/missions/{bid}/verify-code',ttok,{'code':created['service_code']})
        await expect(page.locator('#stage-5')).to_be_visible()
        started = (await booking(setup.request,token,bid))['service_started_at']
        await api(setup.request,'POST',f'/translator/missions/{bid}/cancel',ttok,status=409)
        assert (await booking(setup.request,token,bid))['status'] == 'matched'

        extend = page.locator('#btn-extend-one-hour')
        await faults('extend',extend)
        await faults('finish',page.locator('#btn-finish-service'),method='GET')
        await expect(page.locator('#stage-6')).to_be_hidden()
        unchanged = await booking(setup.request,token,bid)
        assert unchanged['hours'] == hours and unchanged['total'] == total and unchanged['pending_extension'] is None
        # Real deadline; no hanging intercepted route after an intentional abort.
        await page.clock.install()
        await page.evaluate("""() => {
            window.serviceTestFetch=window.fetch;window.serviceTestPost=false;window.serviceTestAborted=false;
            window.fetch=(url,opts)=>{
                if(url.endsWith('/extend')&&opts.method==='POST')return new Promise((resolve,reject)=>{
                    window.serviceTestPost=true;opts.signal.addEventListener('abort',()=>{
                        window.serviceTestAborted=true;reject(new DOMException('Aborted','AbortError'));
                    },{once:true});
                });
                return window.serviceTestFetch(url,opts);
            };
        }""")
        await extend.click()
        await page.wait_for_function('() => window.serviceTestPost')
        await page.clock.fast_forward(10001)
        await expect(extend).to_be_enabled()
        await expect(page.locator('#toast-text')).to_have_text(ERROR[lang])
        assert await page.evaluate('window.serviceTestAborted')
        await page.evaluate('window.fetch=window.serviceTestFetch')
        await page.clock.resume()

        # All service controls and card actions share one pending-operation lock.
        entered = asyncio.Event()
        async def delayed(route):
            entered.set(); await release.wait(); await route.continue_()
        await page.route(f'**/api/traveler/bookings/{bid}/extend',delayed)
        count = len(posts)
        await extend.click(); await entered.wait()
        for id in ['btn-extend-one-hour','btn-finish-service','btn-approve-finish','btn-reject-finish']:
            await expect(page.locator('#'+id)).to_be_disabled()
            await page.locator('#'+id).dispatch_event('click')
        await page.clock.fast_forward(2001)
        await page.clock.resume()
        await expect(extend).to_be_disabled()  # The timer's UI loop must not unlock it.
        assert len(posts) == count+1
        waiting = await booking(setup.request,token,bid)
        assert waiting['hours'] == hours and waiting['total'] == total and waiting['pending_extension'] is None
        release.set()
        await page.wait_for_function("id => {const b=JSON.parse(localStorage.getItem('hamzaban.bookings.v1')).find(x=>x.serverId===id);return !!b.pendingExtension;}",arg=bid)
        await page.unroute(f'**/api/traveler/bookings/{bid}/extend',delayed)
        pending_ext = (await booking(setup.request,token,bid))['pending_extension']
        assert pending_ext and (await booking(setup.request,token,bid))['total'] == total
        await api(setup.request,'POST',f"/translator/extensions/{pending_ext['id']}/reject",ttok)
        await expect(extend).to_be_enabled()
        assert (await booking(setup.request,token,bid))['hours'] == hours
        await extend.click()
        await page.wait_for_function("id => !!JSON.parse(localStorage.getItem('hamzaban.bookings.v1')).find(x=>x.serverId===id).pendingExtension",arg=bid)
        next_ext = (await booking(setup.request,token,bid))['pending_extension']
        assert next_ext['id'] != pending_ext['id']
        await api(setup.request,'POST',f"/translator/extensions/{next_ext['id']}/accept",ttok)
        await page.wait_for_function("([id,h])=>JSON.parse(localStorage.getItem('hamzaban.bookings.v1')).find(x=>x.serverId===id).hoursNum===h",arg=[bid,hours+1])
        extended = await booking(setup.request,token,bid)
        assert extended['total'] > total and extended['service_started_at'] == started
        total = extended['total']

        # Reject/approve translator finish and own early finish are never local.
        await api(setup.request,'POST',f'/translator/missions/{bid}/finish',ttok,status=202)
        await expect(page.locator('#finish-request-banner')).to_be_visible()
        await faults('finish-reject',page.locator('#btn-reject-finish'))
        assert (await booking(setup.request,token,bid))['finish_requested'] is True
        await page.locator('#btn-reject-finish').click()
        await expect(page.locator('#finish-request-banner')).to_be_hidden()
        await faults('finish',page.locator('#btn-finish-service'))
        await expect(page.locator('#stage-6')).to_be_hidden()
        assert (await booking(setup.request,token,bid))['status'] == 'matched'
        await api(setup.request,'POST',f'/translator/missions/{bid}/finish',ttok,status=202)
        await expect(page.locator('#finish-request-banner')).to_be_visible()
        await faults('finish-approve',page.locator('#btn-approve-finish'))
        await page.locator('#btn-approve-finish').click()
        await expect(page.locator('#stage-6')).to_be_visible()
        finished = await booking(setup.request,token,bid)
        assert finished['status'] == 'finished' and finished['finished_by']=='translator' and finished['total']==total
        assert (await booking(setup.request,token,old['id']))['status']=='cancelled'

        # A late real finish receipt must not read/mutate the replacement account.
        new = await api(setup.request,'POST','/traveler/bookings',token,
                        {'kind':'instant','origin_lang':'ar','dest_lang':'fa','place':'late-service-response'},status=201)
        offers = await api(setup.request,'GET','/translator/offers',ttok)
        await api(setup.request,'POST',f"/translator/offers/{offers['offers'][0]['id']}/accept",ttok)
        await api(setup.request,'POST',f"/translator/missions/{new['id']}/verify-code",ttok,{'code':new['service_code']})
        await page.reload(); await expect(page.locator('#stage-5')).to_be_visible()
        replacement = await sign_in(setup.request,'9'+str(secrets.randbelow(900000000)+100000000))
        release.clear(); entered.clear()
        await page.route(f"**/api/traveler/bookings/{new['id']}/finish",delayed)
        await page.locator('#btn-finish-service').click(); await entered.wait()
        await page.evaluate("""s=>{
            localStorage.setItem('hamzaban.token.v1',s.token);
            localStorage.setItem('hamzaban.user.v1',JSON.stringify({name:'New',last:'Account',gender:'مرد',phone:s.user.phone,authUserId:s.user.id}));
            localStorage.setItem('hamzaban.bookings.v1','[]');document.getElementById('toast-text').textContent='';
        }""",replacement)
        release.set()
        await expect(page.locator('#btn-finish-service')).to_be_enabled()
        assert await page.evaluate("localStorage.getItem('hamzaban.token.v1')")==replacement['token']
        assert await page.evaluate("localStorage.getItem('hamzaban.bookings.v1')")=='[]'
        final=await booking(setup.request,token,new['id'])
        assert final['status']=='finished' and final['finished_by']=='traveler' and final['total']==new['total']
        await expect(page.locator('#stage-6')).to_be_hidden()
        assert not errors,errors
        print(f'PASS [{lang}]: no local service simulation, pinned security code, real start/extension consent/full-price finish, safe failures/timeouts/locks and late-session isolation')
    except Exception:
        print('JavaScript errors:',errors)
        if page:
            ARTIFACTS.mkdir(parents=True,exist_ok=True)
            await page.screenshot(path=str(ARTIFACTS/f'{lang}.png'),full_page=True)
        raise
    finally:
        release.set()
        if ctx:
            await page.unroute_all(behavior='ignoreErrors')
            await ctx.close()
        await setup.close()

async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser=await p.chromium.launch(args=['--no-sandbox'])
        for lang in ['fa','en','ar']:
            await scenario(browser,lang)
        await browser.close()

if __name__=='__main__':
    asyncio.run(main())
