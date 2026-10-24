const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const read = (name) => fs.readFileSync(path.join(root, name), 'utf8');
const uiSource = read('translator/ui.js');

test('shared translator auth helper sends both server-supported session headers', () => {
  const context = vm.createContext({
    window: {},
    localStorage: { getItem() { return null; }, setItem() {} }
  });
  vm.runInContext(uiSource, context, { filename: 'translator/ui.js' });

  const extra = { 'Content-Type': 'application/json' };
  const actual = context.window.HZ.authHeaders('session-token', extra);
  assert.deepEqual({ ...actual }, {
    'Content-Type': 'application/json',
    Authorization: 'Bearer session-token',
    'X-Auth-Token': 'session-token'
  });
  assert.deepEqual(extra, { 'Content-Type': 'application/json' });
  assert.deepEqual({ ...context.window.HZ.authHeaders('', extra) }, extra);
  assert.deepEqual({ ...context.window.HZ.authHeaders(null) }, {});
});

test('every authenticated translator workspace client uses the shared dual-header helper', () => {
  const app = read('translator/app.js');
  assert.match(app, /fetch\('\/api\/translator\/missions',\s*\{\s*headers:\s*H\.authHeaders\(st\.token\)/);
  assert.match(app, /fetch\('\/api\/translator\/payments',\s*\{\s*headers:\s*H\.authHeaders\(token\)/);
  assert.match(app, /headers:\s*H\.authHeaders\(t,\s*\{\s*'Content-Type':\s*'application\/json'/);
  assert.doesNotMatch(app, /headers:\s*\{\s*Authorization\s*:/);

  for (const file of ['translator/mission-actions.js', 'translator/presence.js', 'translator/notifications.js']) {
    const source = read(file);
    assert.match(source, /window\.HZ\.authHeaders\(/, `${file} should use the shared session-header helper`);
    assert.doesNotMatch(source, /headers:\s*\{\s*Authorization\s*:/, `${file} should not send Authorization alone`);
  }

  const entry = read('translator/index.html');
  assert.match(entry, /var headers = H\.authHeaders\(state\.token,\s*\{\s*'Content-Type':\s*'application\/json'/);
  assert.match(entry, /X-Auth-Token/, 'the development approval request also keeps the proxy fallback header');
});

test('translator service-worker cache and entry script use the bumped version', () => {
  const entry = read('translator/index.html');
  const workspace = read('translator/app.html');
  const serviceWorker = read('translator/sw.js');
  assert.match(entry, /<script src="ui\.js\?v=50"><\/script>/);
  assert.match(workspace, /<script src="ui\.js\?v=50"><\/script>/);
  assert.match(serviceWorker, /hz-translator-v50/);
  assert.match(serviceWorker, /ui\.js\?v=50/);
  assert.doesNotMatch(workspace + serviceWorker, /\?v=49|hz-translator-v49/);
});
