'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.join(__dirname, '..');
const signInSource = fs.readFileSync(path.join(root, 'traveler/index.html'), 'utf8');
const appSource = fs.readFileSync(path.join(root, 'traveler/app.html'), 'utf8');

test('traveler sign-in and app API helpers send the proxy-safe session header', () => {
  assert.match(
    signInSource,
    /if \(tk\) \{\s*headers\.Authorization = 'Bearer ' \+ tk;\s*headers\['X-Auth-Token'\] = tk;/,
    'session restore must send X-Auth-Token alongside Authorization'
  );
  assert.match(
    appSource,
    /var headers = \{\s*'Content-Type': 'application\/json', Authorization: 'Bearer ' \+ t, 'X-Auth-Token': t\s*\};/,
    'authenticated traveler API calls must send X-Auth-Token alongside Authorization'
  );
});
