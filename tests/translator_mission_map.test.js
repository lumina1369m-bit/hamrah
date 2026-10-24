'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'translator/mission-map.js'), 'utf8');
const workspaceHTML = fs.readFileSync(path.join(root, 'translator/app.html'), 'utf8');
const appSource = fs.readFileSync(path.join(root, 'translator/app.js'), 'utf8');
const styleSource = fs.readFileSync(path.join(root, 'translator/workspace.css'), 'utf8');
const serverSource = fs.readFileSync(path.join(root, 'server/server.js'), 'utf8');

function createFixture(origin = 'https://preview.example') {
  const elements = {
    'translator-map': { style: {}, offsetWidth: 360, offsetHeight: 720 },
    'translator-map-placeholder': { hidden: false },
    'translator-map-placeholder-title': { textContent: '' },
    'translator-map-placeholder-note': { textContent: '' },
    'translator-map-location': { hidden: true },
    'translator-map-label': { textContent: '' },
    'translator-map-open': { hidden: true, href: '' },
    'translator-map-zoom-in': { disabled: true },
    'translator-map-zoom-out': { disabled: true },
    'translator-map-recenter': { disabled: true }
  };
  let mapCreated = 0;
  const mapState = {
    center: null,
    zoom: 0,
    layers: [],
    removed: [],
    setView(center, zoom) { this.center = center.slice(); this.zoom = zoom; return this; },
    setZoom(zoom) { this.zoom = zoom; return this; },
    getZoom() { return this.zoom; },
    invalidateSize() { this.invalidated = true; },
    removeLayer(layer) { this.removed.push(layer); if (this.marker === layer) this.marker = null; }
  };
  const L = {
    map(_element, options) { mapCreated++; mapState.options = options; return mapState; },
    tileLayer(url, options) {
      const layer = { url, options, addTo(map) { map.layers.push(this); return this; } };
      return layer;
    },
    marker(latlng, options) {
      return {
        latlng: latlng.slice(), options, tooltip: null,
        addTo(map) { map.marker = this; return this; },
        setLatLng(next) { this.latlng = next.slice(); return this; },
        bindTooltip(content, tooltipOptions) { this.tooltip = { content, options: tooltipOptions }; return this; },
        setTooltipContent(content) { if (this.tooltip) this.tooltip.content = content; return this; }
      };
    }
  };
  const window = {
    origin,
    L,
    requestAnimationFrame(callback) { callback(); },
    addEventListener() {}
  };
  const document = { getElementById(id) { return elements[id] || null; } };
  vm.runInNewContext(source, { window, document }, { filename: 'mission-map.js' });
  return { elements, window, mapState, get mapCreated() { return mapCreated; } };
}

test('does not create or center a map before server coordinates are available', () => {
  const f = createFixture();
  assert.equal(f.mapCreated, 0);
  assert.equal(f.elements['translator-map-placeholder'].hidden, false);
  assert.equal(f.elements['translator-map'].style.visibility, 'hidden');
  assert.equal(f.elements['translator-map-zoom-in'].disabled, true);
  assert.equal(f.window.HZ_TRANSLATOR_MAP.setMission({ lat: '35.6997', lng: 51.338 }), false);
  assert.equal(f.mapCreated, 0);
});

test('uses the shared OpenStreetMap tiles and only the accepted mission point', () => {
  const f = createFixture();
  const mission = { reservation_id: 42, lat: 35.6997, lng: 51.338, place: 'نشانی ثبت‌شدهٔ سرور' };
  assert.equal(f.window.HZ_TRANSLATOR_MAP.setMission(mission), true);
  assert.equal(f.mapCreated, 1);
  assert.deepEqual(Array.from(f.mapState.center), [mission.lat, mission.lng]);
  assert.equal(f.mapState.zoom, 16);
  assert.equal(f.mapState.layers[0].url, 'https://tile.openstreetmap.org/{z}/{x}/{y}.png');
  assert.equal(f.mapState.marker.latlng[0], mission.lat);
  assert.equal(f.mapState.marker.latlng[1], mission.lng);
  assert.equal(f.mapState.marker.tooltip.content, mission.place);
  assert.equal(f.mapState.marker.tooltip.options.permanent, true);
  assert.equal(f.elements['translator-map-placeholder'].hidden, true);
  assert.equal(f.elements['translator-map-location'].hidden, false);
  assert.equal(f.elements['translator-map-label'].textContent, mission.place);
  assert.equal(f.elements['translator-map-open'].hidden, false);
  assert.match(f.elements['translator-map-open'].href, /mlat=35\.6997&mlon=51\.338/);
  assert.equal(f.elements['translator-map-zoom-in'].disabled, false);
  f.window.HZ_TRANSLATOR_MAP.zoom(1);
  assert.equal(f.mapState.zoom, 17);
  f.window.HZ_TRANSLATOR_MAP.reset();
  assert.equal(f.mapState.zoom, 16);
});

test('clears a previous pin and refuses invalid coordinates instead of leaving stale location data', () => {
  const f = createFixture();
  f.window.HZ_TRANSLATOR_MAP.setMission({ reservation_id: 7, lat: 40, lng: -73, place: 'نشانی واقعی' });
  const marker = f.mapState.marker;
  assert.equal(f.window.HZ_TRANSLATOR_MAP.setMission({ lat: 91, lng: -73, place: 'مختصات نامعتبر' }, {
    title: 'مختصات در دسترس نیست', note: 'مختصات معتبر از سرور نیامده است.'
  }), false);
  assert.equal(f.mapState.removed.includes(marker), true);
  assert.equal(f.elements['translator-map'].style.visibility, 'hidden');
  assert.equal(f.elements['translator-map-placeholder'].hidden, false);
  assert.equal(f.elements['translator-map-placeholder-title'].textContent, 'مختصات در دسترس نیست');
  assert.equal(f.elements['translator-map-location'].hidden, true);
  assert.equal(f.elements['translator-map-open'].hidden, true);
  assert.equal(f.elements['translator-map-zoom-in'].disabled, true);
  assert.equal(f.elements['translator-map-recenter'].disabled, true);
});

test('the signed-in workspace uses the reference drawer, local assets and server-backed cards', () => {
  for (const id of ['translator-map-stage', 'mission-sheet', 'translator-sheet-toggle', 'sheet-scroll-area',
    'workspace-sheet-state', 'workspace-sheet-meta', 'offers-box', 'missions-list', 'payments-box',
    'shift-toggle-btn', 'header-profile-btn', 'header-financial-shortcut']) {
    assert.match(workspaceHTML, new RegExp(`id="${id}"`), `missing #${id}`);
  }
  assert.match(workspaceHTML, /class="translator-workspace-sheet sheet-expanded"/);
  assert.match(workspaceHTML, /class="translator-header-capsule"/);
  assert.match(workspaceHTML, /class="translator-sheet-topline"/);
  assert.match(workspaceHTML, /translator-map-grid/);
  assert.match(workspaceHTML, /<main id="view-workspace" class="translator-workspace-view">/);
  assert.doesNotMatch(workspaceHTML, /id="mobile-nav"|id="desktop-nav"/);
  assert.doesNotMatch(workspaceHTML, /https:\/\/(?:cdn\.|unpkg\.com|fonts\.googleapis)/);
  for (const asset of ['mission-map.js', 'mission-actions.js', 'presence.js', 'notifications.js', 'support.js', 'app.js', 'config-features.js']) {
    assert.ok(workspaceHTML.includes(`src="${asset}?v=46"`), `missing versioned local script ${asset}`);
  }
  assert.match(styleSource, /\.translator-map-grid/);
  assert.match(styleSource, /\.translator-workspace-sheet/);
  assert.match(appSource, /Object\.prototype\.hasOwnProperty\.call\(m, 'reservation_id'\)/);
  assert.match(appSource, /window\.HZ_TRANSLATOR_MAP\.setMission\(selected/);
  assert.match(appSource, /data-service-clock/);
  assert.match(appSource, /serverClockOffset/);
  assert.match(appSource, /setInterval\(loadMissions, 5000\)/);
  assert.match(appSource, /این درخواست خدمت را پایان نمی‌دهد/);
  assert.doesNotMatch(workspaceHTML + appSource, /الشيخ|احمد المنصور|اسپیناس|۳,۲۰۰,۰۰۰|۴,۸۰۰,۰۰۰|سارا رادمنش|M-1001|MAT-030|service_code/);
  assert.match(serverSource, /OR service_started_at IS NOT NULL/);
  assert.match(serverSource, /server_time: new Date\(serverTime\)/);
});

test('map controller contains no route drawing or device geolocation implementation', () => {
  assert.doesNotMatch(source, /L\.polyline|navigator\.geolocation|watchPosition\s*\(/);
});
