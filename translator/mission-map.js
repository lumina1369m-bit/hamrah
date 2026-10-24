/*
 * Interpreter mission map.
 * Uses the same Leaflet build and OpenStreetMap tile layer as traveler/app.html.
 * No route, ETA, vehicle marker, or live device location is synthesized here.
 */
(function (w, d) {
  'use strict';

  var mapEl = d.getElementById('translator-map');
  var placeholder = d.getElementById('translator-map-placeholder');
  var titleEl = d.getElementById('translator-map-placeholder-title');
  var noteEl = d.getElementById('translator-map-placeholder-note');
  var locationBox = d.getElementById('translator-map-location');
  var locationLabel = d.getElementById('translator-map-label');
  var externalLink = d.getElementById('translator-map-open');
  var zoomIn = d.getElementById('translator-map-zoom-in');
  var zoomOut = d.getElementById('translator-map-zoom-out');
  var recenter = d.getElementById('translator-map-recenter');

  var map = null;
  var marker = null;
  var tileLayer = null;
  var current = null;
  var lastCenter = null;

  function setPlaceholder(title, note) {
    if (titleEl) titleEl.textContent = title || 'نقشهٔ محل ملاقات';
    if (noteEl) noteEl.textContent = note || 'پس از پذیرش مأموریت، اگر مختصات واقعی محل در سرور ثبت شده باشد، اینجا نمایش داده می‌شود.';
    if (placeholder) placeholder.hidden = false;
    if (mapEl) mapEl.style.visibility = 'hidden';
    if (locationBox) locationBox.hidden = true;
    if (externalLink) externalLink.hidden = true;
    if (zoomIn) zoomIn.disabled = true;
    if (zoomOut) zoomOut.disabled = true;
    if (recenter) recenter.disabled = true;
    if (marker && map) map.removeLayer(marker);
    marker = null;
    current = null;
  }

  function validCoordinates(mission) {
    return !!mission && typeof mission.lat === 'number' && Number.isFinite(mission.lat) &&
      typeof mission.lng === 'number' && Number.isFinite(mission.lng) &&
      mission.lat >= -90 && mission.lat <= 90 && mission.lng >= -180 && mission.lng <= 180;
  }

  function ensureMap() {
    if (map) return map;
    if (!w.L || !mapEl) return null;

    map = w.L.map(mapEl, {
      zoomControl: false,
      minZoom: 5,
      maxZoom: 19,
      attributionControl: true
    });
    mapEl.style.visibility = 'visible';

    // Keep the exact same public map provider/configuration as the passenger map.
    if (w.origin !== 'null') {
      tileLayer = w.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        referrerPolicy: 'strict-origin-when-cross-origin',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      }).addTo(map);
    }
    return map;
  }

  function setMission(mission, options) {
    options = options || {};
    if (!validCoordinates(mission)) {
      setPlaceholder(options.title, options.note);
      return false;
    }

    var activeMap = ensureMap();
    if (!activeMap) {
      setPlaceholder('نقشه بارگذاری نشد', 'کتابخانهٔ نقشه در دسترس نیست؛ اطلاعات مکانی ساختگی نمایش داده نمی‌شود.');
      return false;
    }

    var latlng = [mission.lat, mission.lng];
    var identity = String(mission.reservation_id || mission.id || mission.lat + ',' + mission.lng);
    var changed = !current || current.identity !== identity || current.lat !== mission.lat || current.lng !== mission.lng;
    var place = typeof mission.place === 'string' && mission.place.trim() ? mission.place.trim() : 'محل ملاقات';

    mapEl.style.visibility = 'visible';
    if (placeholder) placeholder.hidden = true;
    if (locationBox) locationBox.hidden = false;
    if (locationLabel) locationLabel.textContent = place;
    if (externalLink) {
      externalLink.href = 'https://www.openstreetmap.org/?mlat=' + encodeURIComponent(mission.lat) +
        '&mlon=' + encodeURIComponent(mission.lng) + '#map=16/' + encodeURIComponent(mission.lat) + '/' + encodeURIComponent(mission.lng);
      externalLink.hidden = false;
    }

    if (!marker) {
      // Leaflet's marker and its label stay at the server-supplied meeting point; there is no route overlay.
      marker = w.L.marker(latlng, { title: place, alt: 'محل ملاقات: ' + place }).addTo(activeMap);
      if (typeof marker.bindTooltip === 'function') {
        marker.bindTooltip(place, { permanent: true, direction: 'top', offset: [0, -14], opacity: .98, className: 'translator-map-tooltip' });
      }
    } else {
      marker.setLatLng(latlng);
      marker.options.title = place;
      marker.options.alt = 'محل ملاقات: ' + place;
      if (typeof marker.setTooltipContent === 'function') marker.setTooltipContent(place);
    }

    if (changed || options.center === true) {
      activeMap.setView(latlng, 16, { animate: false });
      lastCenter = latlng;
    }

    current = { identity: identity, lat: mission.lat, lng: mission.lng, place: place };
    if (zoomIn) zoomIn.disabled = false;
    if (zoomOut) zoomOut.disabled = false;
    if (recenter) recenter.disabled = false;

    // The app can switch tabs while a map container is hidden; measure it after paint.
    w.requestAnimationFrame(function () {
      if (map && mapEl && mapEl.offsetWidth && mapEl.offsetHeight) map.invalidateSize({ pan: false });
    });
    return true;
  }

  function zoom(delta) {
    if (!map || !current) return;
    map.setZoom(Math.max(5, Math.min(19, map.getZoom() + Number(delta || 0))));
  }

  function reset() {
    if (!map || !current || !lastCenter) return;
    map.setView(lastCenter, 16, { animate: false });
  }

  function invalidateSize() {
    if (!map || !current) return;
    w.requestAnimationFrame(function () {
      if (map && mapEl && mapEl.offsetWidth && mapEl.offsetHeight) map.invalidateSize({ pan: false });
    });
  }

  setPlaceholder();
  w.HZ_TRANSLATOR_MAP = {
    setMission: setMission,
    setPlaceholder: setPlaceholder,
    zoom: zoom,
    reset: reset,
    invalidateSize: invalidateSize
  };

  w.addEventListener('resize', invalidateSize);
})(window, document);
