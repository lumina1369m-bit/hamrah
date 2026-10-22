# کمک‌های مشترک تست مترجم: ورود از طریق API سرور و تزریق ماموریت (فقط تست)
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
