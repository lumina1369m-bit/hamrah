# تست ماموریت‌های من: داده‌ها از طریق API سرور (نه localStorage) وارد می‌شوند.
import asyncio, re, json, random, datetime
from playwright.async_api import async_playwright

def iso(days, hours):
    d = datetime.datetime(2026, 10, 20, 10, 0) + datetime.timedelta(days=days, hours=hours)
    return d.strftime('%Y-%m-%dT%H:%M:00')

MISSIONS = [
  {'code': 'M-1001', 'purpose': 'مذاکره تجاری', 'travelerName': 'Christopher Reid', 'place': 'نمایشگاه تهران', 'startAt': iso(5, 0), 'total': 3200000, 'net': 2560000, 'status': 'accepted'},
  {'code': 'M-1002', 'purpose': 'پزشکی', 'travelerName': 'Ali', 'place': 'بیمارستان', 'startAt': iso(6, 0), 'total': 900000, 'net': 720000, 'status': 'pending_invite'},
  {'code': 'M-0999', 'purpose': 'گذشته', 'travelerName': 'Old', 'place': 'x', 'startAt': iso(-10, 0), 'total': 100, 'net': 80, 'status': 'accepted'},
]

# ورود کامل از طریق API و فعال‌سازی مترجم (فقط برای تست)
LOGIN_JS = """async (phone) => {
  const H = {'Content-Type': 'application/json'};
  await fetch('/api/auth/request-code', {method: 'POST', headers: H, body: JSON.stringify({phone, role: 'translator'})});
  const v = await (await fetch('/api/auth/verify', {method: 'POST', headers: H, body: JSON.stringify({phone, role: 'translator', code: '123456'})})).json();
  if (!v.token) return null;
  const st = HZ.load(); st.token = v.token; st.session = {phone, until: Date.now() + 3600e3}; st.completed[1] = true; HZ.save(st);
  await fetch('/api/dev/approve-translator', {method: 'POST', headers: {Authorization: 'Bearer ' + v.token}});
  st.status = 'active_general'; st.profile = {nameFa: 'علی', lastFa: 'رضایی'}; HZ.save(st);
  return v.token;
}"""
SEED_JS = """async ([token, list]) => {
  for (const m of list) {
    await fetch('/api/dev/missions', {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + token}, body: JSON.stringify(m)});
  }
  return true;
}"""

async def run(w, missions, label):
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width': w, 'height': 900})
        await ctx.route(re.compile(r'https://(unpkg\.com|cdn\.|fonts\.).*'), lambda r: r.abort())
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:140]))
        await pg.goto('http://127.0.0.1:8081/translator/index.html'); await pg.wait_for_timeout(600)
        phone = '9' + str(random.randint(100000000, 999999999))
        token = await pg.evaluate(LOGIN_JS, phone)
        assert token, 'ورود از طریق API ناموفق بود'
        if missions:
            await pg.evaluate(SEED_JS, [token, missions])
        await pg.goto('http://127.0.0.1:8081/translator/app.html'); await pg.wait_for_timeout(1500)
        info = await pg.evaluate("""()=>{const L=document.getElementById('missions-list');
          const cards=[...L.children].map(c=>c.textContent.replace(/\\s+/g,' ').trim());
          return {url: location.pathname.split('/').pop(), count: L.children.length, cards, sampleHidden: document.getElementById('missions-sample').classList.contains('hidden'),
                  inCalendar: !!document.getElementById('calendar-section').querySelector('#missions-list')}}""")
        print(label, json.dumps(info, ensure_ascii=False))
        print('  errors:', [e for e in errs if 'tailwind' not in e] or 'none')
        await b.close()

async def main():
    await run(390, MISSIONS, 'with missions 390')
    await run(1280, MISSIONS, 'with missions 1280')
    await run(390, [], 'empty 390')
asyncio.run(main())
