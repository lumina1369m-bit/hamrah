'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.join(__dirname, '..');
const exists = (relative) => fs.existsSync(path.join(root, relative));
const loginHTML = fs.readFileSync(path.join(root, 'translator/index.html'), 'utf8');

test('removes only the translator app and preserves both entry pages', () => {
  assert.equal(exists('translator/app.html'), false, 'authenticated translator app should be removed');
  assert.equal(exists('translator/mission-actions.js'), false);
  assert.equal(exists('translator/mission-map.js'), false);
  assert.equal(exists('translator/workspace.css'), false);
  assert.equal(exists('translator/index.html'), true, 'translator login and registration page must remain');
  assert.equal(exists('translator/ui.js'), true, 'login/registration runtime must remain');
  assert.equal(exists('traveler/index.html'), true, 'traveler login page must remain unchanged');
  assert.equal(exists('traveler/app.html'), true, 'traveler app must remain unchanged');
  assert.match(loginHTML, /id="mobileInput"/);
  assert.match(loginHTML, /id="sendOtpBtn"/);
  assert.match(loginHTML, /finishRegistration\(\)/);
  assert.match(loginHTML, /<script src="ui\.js"><\/script>/);
});
