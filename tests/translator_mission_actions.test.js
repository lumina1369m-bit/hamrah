'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const root = path.join(__dirname, '..');
const actionsSource = fs.readFileSync(path.join(root, 'translator/mission-actions.js'), 'utf8');
const appSource = fs.readFileSync(path.join(root, 'translator/app.js'), 'utf8');
const ERROR = 'نتیجهٔ عملیات تأیید نشد. وضعیت مأموریت را بررسی کنید و سپس دوباره تلاش کنید.';

function createRunner(action, serverTimeOffset) {
  const clientNow = 100_000;
  const serverExpiredAt = new Date(clientNow + 4_000).toISOString();
  const requests = [];
  const toasts = [];
  const token = 'translator-session';
  const mission = {
    reservation_id: 42, status: 'matched', started: true, finish_requested: false,
    arrived_at: null, service_started_at: new Date(clientNow - 10_000).toISOString(),
    hours: 1, total: 100, net: 80,
    details: {
      scheduled_at: null, place: 'Old meeting place', origin_lang: 'fa', dest_lang: 'en',
      field: 'general', hours: 1, car: 0, party: 1, gender_pref: 'any', notes: ''
    }
  };
  const change = {
    id: 88, reservation_id: 42, status: 'pending', expires_at: serverExpiredAt,
    changes: { place: 'New meeting place' }
  };
  const offer = {
    id: 77, reservation_id: 42, status: 'pending', assigned: false,
    expires_at: serverExpiredAt, net: 80
  };
  const extension = {
    id: 99, reservation_id: 42, status: 'pending', extra_hours: 1,
    extra_total: 100, extra_net: 80, expires_at: serverExpiredAt
  };
  const FakeDate = class extends Date {
    static now() { return clientNow; }
  };
  function reply(data) { return { ok: true, status: 200, json: async () => data }; }
  const sandbox = {
    window: {
      HZ: {
        load: () => ({ token }),
        authHeaders: () => ({ Authorization: 'Bearer ' + token }),
        toast: (message) => toasts.push(message)
      }
    },
    document: { querySelectorAll: () => [] },
    Date: FakeDate,
    AbortController,
    fetch: async (url, options) => {
      requests.push({ url, method: options.method });
      if (options.method === 'POST') return reply({ ok: true });
      if (url.endsWith('/offers/77')) return reply(offer);
      if (url.endsWith('/changes/88')) return reply(change);
      if (url.endsWith('/extensions/99')) return reply(extension);
      if (url.endsWith('/missions/42')) return reply(mission);
      throw new Error('Unexpected test request: ' + url);
    },
    setTimeout,
    clearTimeout
  };
  vm.runInNewContext(actionsSource, sandbox, { filename: 'translator/mission-actions.js' });
  const options = {
    action, reservation_id: 42, id: action === 'offer-accept' ? 77 : action === 'change-accept' ? 88 : 99,
    token, serverTimeOffset
  };
  if (action === 'offer-accept') options.net = 80;
  if (action === 'change-accept') options.changes = { place: 'New meeting place' };
  return { run: () => sandbox.window.HZ_MISSION_ACTION.run(options), requests, toasts };
}

test('offer, change and extension expiry guards use the server-clock offset, not a skewed client clock', async () => {
  // The browser clock is four seconds before expiry, but the server is five
  // seconds ahead. Each operation must stop before sending its mutation.
  for (const action of ['offer-accept', 'change-accept', 'accept']) {
    const runner = createRunner(action, 5_000);
    await runner.run();
    assert.equal(runner.requests.filter((request) => request.method === 'POST').length, 0, action);
    assert.deepEqual(runner.toasts, [ERROR], action);
  }
});

test('translator operation callers pass the offer endpoint server-time offset into expiry checks', () => {
  assert.match(appSource, /serverTimeOffset:\s*offerServerClockOffset/);
  assert.match(actionsSource, /Date\.parse\(before\.expires_at\)\s*<=\s*serverNow\(options\.serverTimeOffset\)/);
  assert.match(actionsSource, /Date\.parse\(e\.expires_at\)\s*<=\s*serverNow\(options\.serverTimeOffset\)/g);
  assert.equal((actionsSource.match(/<= serverNow\(options\.serverTimeOffset\)/g) || []).length, 3);
});
