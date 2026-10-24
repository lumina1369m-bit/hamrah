'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.join(__dirname, '..');
const read = (name) => fs.readFileSync(path.join(root, name), 'utf8');
const appHTML = read('translator/app.html');
const settingsSource = read('translator/settings.js');
const serverSource = read('server/server.js');

test('translator settings expose the three passenger-gender choices in the new workspace', () => {
  assert.match(appHTML, /id="view-settings"/);
  assert.match(appHTML, /id="translator-traveler-gender-pref"/);
  assert.match(appHTML, /<option value="any">فرقی نمی‌کند؛ مرد یا زن<\/option>/);
  assert.match(appHTML, /<option value="male">فقط مسافران مرد<\/option>/);
  assert.match(appHTML, /<option value="female">فقط مسافران زن<\/option>/);
  assert.match(appHTML, /switchView\('settings'\)/);
  assert.match(appHTML, /'settings'\]\.?forEach/);
});

test('settings read and save the selected preference through authenticated server requests', () => {
  assert.match(settingsSource, /fetch\('\/api\/translator\/preferences'/);
  assert.match(settingsSource, /request\('PATCH', actor, \{ traveler_gender_pref: value \}\)/);
  assert.match(settingsSource, /window\.HZ\.authHeaders\(actor/);
  assert.match(settingsSource, /traveler_gender_pref: value/);
  assert.match(settingsSource, /تنظیم ذخیره شد و برای پیشنهادهای جدید اعمال می‌شود/);
  assert.match(appHTML, /<script src="settings\.js\?v=51"><\/script>/);
});

test('the server validates, persists, and applies the translator preference to new matching', () => {
  assert.match(serverSource, /ALTER TABLE translators ADD COLUMN traveler_gender_pref TEXT NOT NULL DEFAULT 'any'/);
  assert.match(serverSource, /route\('GET', '\/api\/translator\/preferences'/);
  assert.match(serverSource, /route\('PATCH', '\/api\/translator\/preferences'/);
  assert.match(serverSource, /TRAVELER_GENDER_PREF = new Set\(\['any', 'female', 'male'\]\)/);
  assert.match(serverSource, /r\.traveler_gender !== acceptedTravelerGender/);
  assert.match(serverSource, /t\.traveler_gender_pref/);
});
