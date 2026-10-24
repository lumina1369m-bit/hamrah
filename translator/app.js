
/* اپ مترجم: اطلاعات حساب و مالی فقط از داده‌های واقعی سرور یا وضعیت صریحِ در دسترس نمایش داده می‌شوند. */
(function () {
  var H = window.HZ;
  var state = H.load();
  if (!H.requireSession(state) || !(state.status === 'active_general' || state.status === 'active_specialized')) {
    location.replace('index.html');
    return;
  }
  /* ماموریت‌های من: فقط ماموریت‌های پذیرفته‌شده و آینده، با مبلغ کل و سهم خالص */
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  var selectedDay = 0;
  function dayStart(i) { var d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + i); return d; }
  function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
  var weekdayFmt = (function () { try { return new Intl.DateTimeFormat('fa-IR', { weekday: 'long' }); } catch (e) { return null; } })();
  function dayName(d) { return weekdayFmt ? weekdayFmt.format(d) : ''; }
  function missionsOn(list, d) { return list.filter(function (m) { return sameDay(new Date(m.startAt), d); }); }
  function renderDayBar(list) {
    var bar = document.getElementById('day-bar');
    if (!bar) return;
    bar.innerHTML = '';
    // Do not imply a personal break/availability when the server has no assignments.
    bar.hidden = !list.length;
    if (!list.length) return;
    for (var i = 0; i < 7; i++) {
      (function (i) {
        var d = dayStart(i), n = missionsOn(list, d).length;
        var label = i === 0 ? 'امروز' : i === 1 ? 'فردا' : i === 2 ? 'پس‌فردا' : HZ.toFa(i) + ' روز دیگر';
        var on = i === selectedDay;
        var btn = el('button', 'flex-1 min-w-[70px] py-2 px-3 rounded-xl text-center transition-colors ' + (on ? 'bg-surface-container-high neu-pressed' : 'bg-surface hover:bg-surface-container-low'));
        btn.type = 'button';
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.appendChild(el('span', 'text-[11px] text-on-surface-variant block', label));
        btn.appendChild(el('span', 'text-[15px] font-bold block ' + (on ? 'text-primary' : 'text-on-surface'), dayName(d)));
        btn.appendChild(el('span', n ? 'text-[11px] text-secondary font-bold' : 'text-[11px] text-outline', n ? HZ.toFa(n) + ' مأموریت' : 'بدون مأموریت ثبت‌شده'));
        btn.addEventListener('click', function () { selectedDay = i; renderMissions(); });
        bar.appendChild(btn);
      })(i);
    }
  }
  // مأموریت‌های آینده و خدمت‌های در حال اجرا از سرور خوانده می‌شوند؛ تایمر از زمان شروع واقعی محاسبه می‌شود.
  var MISSIONS = [];
  var missionsState = 'loading'; // loading | ok | error | nosession
  var missionRead = 0;
  var missionsSignature = '';
  var serverClockOffset = 0;
  var selectedMapMissionKey = null;
  function hasMissionCoordinates(m) {
    return !!m && Number.isSafeInteger(m.reservation_id) && m.reservation_id > 0 &&
      typeof m.lat === 'number' && Number.isFinite(m.lat) && m.lat >= -90 && m.lat <= 90 &&
      typeof m.lng === 'number' && Number.isFinite(m.lng) && m.lng >= -180 && m.lng <= 180;
  }
  function missionMapKey(m) { return String(m && m.reservation_id || ''); }
  function updateTranslatorMap(forceCenter) {
    if (!window.HZ_TRANSLATOR_MAP) return;
    var mapped = MISSIONS.filter(hasMissionCoordinates);
    var selected = mapped.find(function (m) { return missionMapKey(m) === selectedMapMissionKey; }) || mapped[0];
    if (selected) {
      selectedMapMissionKey = missionMapKey(selected);
      window.HZ_TRANSLATOR_MAP.setMission(selected, { center: !!forceCenter });
      return;
    }
    var title = 'نقشهٔ محل ملاقات';
    var note = 'نقشهٔ پایه نمایش داده می‌شود؛ پس از پذیرش مأموریت و دریافت مختصات معتبر از سرور، محل ملاقات روی نقشه نشان داده می‌شود.';
    var offers = typeof lastOffers !== 'undefined' && Array.isArray(lastOffers) ? lastOffers : [];
    if (MISSIONS.length) {
      title = 'مختصات در دسترس نیست';
      note = 'نقشهٔ پایه بدون نشانگر می‌ماند؛ مختصات محل از سرور ارائه نشده است. نشانی ثبت‌شده در کارت مأموریت قابل مشاهده است.';
    } else if (offers.length) {
      title = 'پیشنهاد مأموریت';
      note = 'برای حفظ حریم خصوصی، نقطهٔ دقیق پیش از پذیرش روی نقشه نمی‌آید. پس از پذیرش، مختصات ثبت‌شدهٔ سرور نمایش داده می‌شود.';
    } else if (typeof offersState !== 'undefined' && offersState === 'error') {
      title = 'پیشنهادها دریافت نشدند';
      note = 'دوباره تلاش کنید؛ نقشهٔ پایه بدون نشانگر می‌ماند و موقعیتی از روی حدس نمایش داده نمی‌شود.';
    } else if (missionsState === 'loading') {
      title = 'در حال بررسی مأموریت‌ها';
      note = 'تا دریافت مختصات معتبر، نشانگر محل ملاقات نمایش داده نمی‌شود.';
    } else if (missionsState === 'error') {
      title = 'مأموریت‌ها دریافت نشدند';
      note = 'نقشهٔ پایه بدون نشانگر می‌ماند؛ پس از برقراری ارتباط، مأموریت‌ها دوباره بررسی می‌شوند.';
    } else if (missionsState === 'nosession') {
      title = 'نشست نیاز به ورود دوباره دارد';
      note = 'برای دیدن محل ملاقات واقعی دوباره وارد شوید؛ نقشهٔ پایه بدون نشانگر می‌ماند.';
    }
    selectedMapMissionKey = null;
    window.HZ_TRANSLATOR_MAP.setPlaceholder(title, note);
  }
  function focusMissionOnMap(m) {
    if (!hasMissionCoordinates(m)) return;
    selectedMapMissionKey = missionMapKey(m);
    updateTranslatorMap(true);
    expandWorkspaceSheet();
    switchView('workspace');
  }
  function loadMissions() {
    var st = HZ.load(), read = ++missionRead;
    if (!st.token) { MISSIONS = []; missionsSignature = ''; serverClockOffset = 0; missionsState = 'nosession'; renderMissions(); return; }
    // Preserve the last confirmed cards while a background refresh is in flight.
    if (missionsState !== 'ok') { missionsState = 'loading'; MISSIONS = []; renderMissions(); }
    fetch('/api/translator/missions', { headers: H.authHeaders(st.token), cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('missions');
        return r.json();
      })
      .then(function (d) {
        if (read !== missionRead || tok() !== st.token) return;
        function validMission(m) {
          if (!m || !Number.isFinite(Date.parse(m.startAt)) || typeof m.total !== 'number' || !Number.isFinite(m.total) || m.total < 0 ||
              typeof m.net !== 'number' || !Number.isFinite(m.net) || m.net < 0) return false;
          if (!Object.prototype.hasOwnProperty.call(m, 'reservation_id')) return true; // توسعه: مأموریت‌های آزمایشی بدون عملیات رزرو
          return Number.isSafeInteger(m.reservation_id) && m.reservation_id > 0 && typeof m.started === 'boolean' &&
            typeof m.finish_requested === 'boolean' && typeof m.hours === 'number' && Number.isFinite(m.hours) && m.hours >= 1 && m.hours <= 24 &&
            (m.started ? typeof m.service_started_at === 'string' && Number.isFinite(Date.parse(m.service_started_at)) : m.service_started_at === null);
        }
        var serverTime = d && Date.parse(d.server_time);
        if (!d || !Number.isFinite(serverTime) || !Array.isArray(d.missions) || !d.missions.every(validMission)) throw new Error('missions');
        serverClockOffset = serverTime - Date.now();
        // Development-only fixture rows have no reservation_id and cannot be acted on.
        // The translator workspace renders only reservation-backed records from the server.
        var nextMissions = d.missions.filter(function (m) {
          return m && Object.prototype.hasOwnProperty.call(m, 'reservation_id');
        }).sort(function (a, b) { return Date.parse(a.startAt) - Date.parse(b.startAt); });
        var signature = JSON.stringify(nextMissions);
        var changed = missionsState !== 'ok' || signature !== missionsSignature;
        MISSIONS = nextMissions;
        missionsSignature = signature;
        missionsState = 'ok';
        if (changed) renderMissions();
        else { updateTranslatorMap(); updateWorkspaceSheetSummary(); updateServiceTimers(); }
      })
      .catch(function () {
        if (read !== missionRead || tok() !== st.token) return;
        MISSIONS = []; missionsSignature = ''; serverClockOffset = 0; missionsState = 'error'; renderMissions();
      });
  }
  function serviceAction(action, m, code, actor) {
    return HZ_MISSION_ACTION.run({ action: action, reservation_id: m.reservation_id,
      id: m.id, code: code, token: actor, refresh: function () { loadMissions(); refreshOffers(true); } });
  }
  function renderMissions() {
    var box = document.getElementById('missions-list');
    if (!box) return;
    var sc = document.getElementById('schedule-list');
    var list = MISSIONS;
    var emptyTxt = missionsState === 'loading' ? 'در حال دریافت ماموریت‌ها…'
      : missionsState === 'error' ? 'دریافت ماموریت‌ها انجام نشد. اتصال اینترنت را بررسی کنید.'
      : missionsState === 'nosession' ? 'نشست شما منقضی شده است. دوباره وارد شوید.'
      : 'فعلاً مأموریت پذیرفته‌شده‌ای ندارید. درخواست‌های جدید بعد از تأیید پذیرفته می‌شوند.';
    var dayList = missionsOn(list, dayStart(selectedDay));
    renderDayBar(list);
    box.innerHTML = '';
    if (sc) sc.innerHTML = '';
    if (!list.length) {
      var hasPendingWork = lastOffers.length || lastChanges.length || lastExtensions.length;
      if (missionsState !== 'ok' || !hasPendingWork) {
        box.appendChild(el('div', 'translator-empty-missions', emptyTxt));
      }
      if (sc) sc.appendChild(el('div', 'rounded-2xl bg-surface p-5 neu-raised text-center text-[13px] text-on-surface-variant md:col-span-3', emptyTxt));
      updateTranslatorMap();
      updateWorkspaceSheetSummary();
      return;
    }
    list.forEach(function (m) { box.appendChild(missionCard(m)); });
    if (sc) {
      if (!dayList.length) sc.appendChild(el('div', 'rounded-2xl bg-surface p-5 neu-raised text-center text-[13px] text-on-surface-variant md:col-span-3', 'در این روز ماموریتی ندارید.'));
      dayList.forEach(function (m) { sc.appendChild(missionCard(m)); });
    }
    updateTranslatorMap();
    updateWorkspaceSheetSummary();
    updateServiceTimers();
  }
  function serviceDuration(milliseconds) {
    var seconds = Math.max(0, Math.floor(milliseconds / 1000));
    var hours = Math.floor(seconds / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    var remainder = seconds % 60;
    return HZ.toFa(String(hours).padStart(2, '0') + ':' + String(minutes).padStart(2, '0') + ':' + String(remainder).padStart(2, '0'));
  }
  function updateServiceTimers() {
    var now = Date.now() + serverClockOffset;
    document.querySelectorAll('[data-service-clock]').forEach(function (timer) {
      var startedAt = Number(timer.getAttribute('data-service-started-at'));
      var hours = Number(timer.getAttribute('data-service-hours'));
      if (!Number.isFinite(startedAt) || !Number.isFinite(hours) || hours < 1 || hours > 24) return;
      var elapsed = Math.max(0, now - startedAt);
      var planned = hours * 3600000;
      var text = 'زمان سپری‌شده: ' + serviceDuration(elapsed) + ' از ' + HZ.toFa(hours) + ' ساعت توافق‌شده';
      if (elapsed >= planned) text += ' — مدت توافق‌شده سپری شده؛ پایان خدمت با مسافر است.';
      timer.textContent = text;
      timer.setAttribute('aria-label', text);
    });
  }
  function missionCard(m) {
    var actor = tok();
    var card = el('div', 'translator-mission-card rounded-2xl bg-surface p-4 sm:p-5 neu-raised flex flex-col gap-3');
    var head = el('div', 'translator-mission-heading flex items-start justify-between gap-2');
    // سرور کد زمینه (general/medical/…) می‌فرستد؛ عنوان فارسی نمایش داده می‌شود
    var FIELD_FA = { general: 'عمومی', medical: 'پزشکی', legal: 'حقوقی', business: 'تجاری' };
    head.appendChild(el('span', 'text-[14px] text-on-surface font-bold', FIELD_FA[m.purpose] || m.purpose || 'ماموریت'));
    card.appendChild(head);
    card.appendChild(el('span', 'text-[11px] text-on-surface-variant', 'مسافر: ' + (m.travelerName || '—')));
    var when = new Date(m.startAt);
    card.appendChild(el('span', 'text-[11px] text-on-surface-variant', (m.place || '') + ' • ' + HZ.jDate(when) + ' ' + HZ.clock(when)));
    // نقشه فقط از مختصات واقعی مأموریت پذیرفته‌شده استفاده می‌کند؛ مسیر و ETA ساخته نمی‌شود.
    if (hasMissionCoordinates(m)) {
      var mapButton = el('button', 'translator-map-focus', 'نمایش محل ملاقات روی نقشه');
      mapButton.type = 'button';
      mapButton.addEventListener('click', function () { focusMissionOnMap(m); });
      card.appendChild(mapButton);
    }
    var money = el('div', 'translator-mission-money flex items-center justify-between pt-2 border-t border-surface-variant/40 text-[12px]');
    var total = el('span', 'text-on-surface-variant', 'مبلغ کل');
    total.appendChild(el('b', '', HZ.money(m.total || 0)));
    var net = el('span', 'font-bold text-secondary', 'سهم شما');
    net.appendChild(el('b', '', HZ.money(m.net || 0)));
    money.appendChild(total); money.appendChild(net);
    card.appendChild(money);
    // شروع خدمت فقط با کد امنیتی‌ای که مسافر اعلام می‌کند؛ تا پیش از آن پایان خدمت ممکن نیست
    if (m.reservation_id && !m.started) {
      var codeRow = el('div', 'translator-service-code-row flex items-center gap-2');
      var codeInp = document.createElement('input');
      codeInp.type = 'text'; codeInp.inputMode = 'numeric'; codeInp.maxLength = 5; codeInp.placeholder = 'کد اعلام‌شده توسط مسافر';
      codeInp.setAttribute('aria-label', 'کد پنج‌رقمی شروع خدمت که مسافر اعلام می‌کند');
      codeInp.className = 'w-32 px-3 py-1.5 rounded-xl neu-inset-shallow bg-surface-container text-center text-[13px] font-bold tracking-widest';
      var codeBtn = el('button', 'px-3 py-1.5 rounded-xl bg-[#006a61] text-white text-[11px] font-bold cursor-pointer', 'ثبت کد و شروع خدمت');
      codeBtn.type = 'button';
      HZ_MISSION_ACTION.bind(codeBtn, m.reservation_id);
      codeBtn.onclick = function () { serviceAction('start', m, codeInp.value, actor); };
      codeRow.appendChild(codeInp); codeRow.appendChild(codeBtn);
      card.appendChild(codeRow);
    }
    if (m.reservation_id && m.started) {
      card.appendChild(el('span', 'self-start px-2.5 py-0.5 rounded-full bg-secondary-fixed/50 text-secondary text-[11px] font-bold', 'خدمت شروع شده'));
      var serviceTimer = el('div', 'translator-service-timer rounded-xl neu-pressed px-3 py-2 text-[12px] font-bold text-on-surface-variant', 'در حال محاسبهٔ زمان خدمت از سرور…');
      serviceTimer.setAttribute('role', 'timer');
      serviceTimer.setAttribute('aria-live', 'off');
      serviceTimer.setAttribute('data-service-clock', '1');
      serviceTimer.setAttribute('data-service-started-at', String(Date.parse(m.service_started_at)));
      serviceTimer.setAttribute('data-service-hours', String(m.hours));
      card.appendChild(serviceTimer);
    }
    if (m.reservation_id && m.started && m.finish_requested) {
      card.appendChild(el('span', 'self-start px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[11px] font-bold', 'درخواست پایان فرستاده شده؛ منتظر تأیید مسافر'));
    }
    if (m.reservation_id && m.started && !m.finish_requested) {
      var finBtn = el('button', 'self-start px-3 py-1.5 rounded-xl bg-[#006a61] text-white text-[11px] font-bold cursor-pointer', 'درخواست پایان خدمت');
      finBtn.type = 'button';
      HZ_MISSION_ACTION.bind(finBtn, m.reservation_id);
      finBtn.onclick = function () { serviceAction('finish', m, undefined, actor); };
      card.appendChild(finBtn);
      card.appendChild(el('span', 'text-[11px] text-on-surface-variant', 'این درخواست خدمت را پایان نمی‌دهد؛ تأیید یا پایان زودهنگام با مسافر است.'));
    }
    if (m.reservation_id && !m.started) {
      var cancelBtn = el('button', 'self-start px-3 py-1.5 rounded-xl neu-raised text-[11px] font-bold text-error cursor-pointer', 'لغو ماموریت');
      cancelBtn.type = 'button';
      HZ_MISSION_ACTION.bind(cancelBtn, m.reservation_id);
      cancelBtn.onclick = function () { serviceAction('cancel', m, undefined, actor); };
      card.appendChild(cancelBtn);
      card.appendChild(el('span', 'text-[11px] text-on-surface-variant', 'لغو پیش از شروع تا ۵ امتیاز کم می‌کند؛ پیدا شدن مترجم جایگزین قطعی نیست.'));
    }
    return card;
  }

  // ---------- پرداخت‌های منتظر تأیید (سند ۷.۳) ----------
  var PAYMENTS_LIST = [], paymentsState = 'loading';
  var paymentRead = 0, paymentApplied = 0, paymentRevision = 0;
  function loadPayments(invalidate) {
    var token = tok(), read = ++paymentRead, revision = invalidate ? ++paymentRevision : paymentRevision;
    if (!token) { PAYMENTS_LIST = []; paymentsState = 'error'; renderPayments(); return; }
    fetch('/api/translator/payments', { headers: H.authHeaders(token), cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('payments'); return r.json(); })
      .then(function (d) {
        if (tok() !== token || revision !== paymentRevision || read < paymentApplied) return;
        if (!d || !Array.isArray(d.payments) || !d.payments.every(function (p) {
          return p && Number.isSafeInteger(p.reservation_id) && p.reservation_id > 0 &&
            typeof p.total === 'number' && Number.isFinite(p.total) && p.total >= 0 &&
            typeof p.net === 'number' && Number.isFinite(p.net) && p.net >= 0 && typeof p.confirmed === 'boolean' &&
            [null, 'cash', 'online'].includes(p.pay_method) && [null, 'awaiting_cash', 'disputed'].includes(p.pay_state) &&
            (p.pay_state === null || p.pay_method === 'cash');
        }) || new Set(d.payments.map(function (p) { return p.reservation_id; })).size !== d.payments.length) throw new Error('payments');
        paymentApplied = read; PAYMENTS_LIST = d.payments; paymentsState = 'ok'; renderPayments();
      })
      .catch(function () {
        if (tok() !== token || revision !== paymentRevision || read < paymentApplied) return;
        paymentApplied = read; PAYMENTS_LIST = []; paymentsState = 'error'; renderPayments();
      });
  }
  function paymentsBox() {
    var box = document.getElementById('payments-box');
    if (!box) {
      var list = document.getElementById('missions-list');
      if (!list || !list.parentNode) return null;
      box = el('div', 'flex flex-col gap-3 w-full'); box.id = 'payments-box';
      list.parentNode.insertBefore(box, list);
    }
    return box;
  }
  function renderPayments() {
    var box = paymentsBox(); if (!box) return;
    box.innerHTML = '';
    if (paymentsState === 'error') {
      box.appendChild(el('span', 'text-[12px] text-error', 'وضعیت پرداخت‌ها دریافت نشد؛ اتصال را بررسی کنید و دوباره تلاش کنید.'));
      var retry = el('button', 'text-[12px] font-bold text-primary', 'دریافت دوبارهٔ پرداخت‌ها');
      retry.type = 'button'; retry.onclick = function () { loadPayments(true); }; box.appendChild(retry);
      return;
    }
    if (!PAYMENTS_LIST.length) {
      box.appendChild(el('span', 'translator-empty-offers', 'پرداخت نیازمند پیگیری از سرور دریافت نشد.'));
      return;
    }
    box.appendChild(el('span', 'text-[13px] font-bold text-on-surface', 'پرداخت‌های منتظر تأیید'));
    PAYMENTS_LIST.forEach(function (p) { box.appendChild(paymentCard(p)); });
  }
  function paymentCard(p) {
    var actor = tok();
    var card = el('div', 'translator-payment-card rounded-2xl bg-surface p-4 neu-raised flex flex-col gap-2');
    card.setAttribute('data-payment-reservation', p.reservation_id);
    card.appendChild(el('span', 'text-[13px] font-bold text-on-surface', p.place || 'ماموریت'));
    card.appendChild(el('span', 'text-[11px] text-on-surface-variant', 'مسافر: ' + (p.travelerName || '—')));
    var money = el('div', 'flex items-center justify-between pt-2 border-t border-surface-variant/40 text-[12px]');
    money.appendChild(el('span', 'text-on-surface-variant', 'مبلغ کل: ' + HZ.money(p.total || 0)));
    money.appendChild(el('span', 'font-bold text-secondary', 'سهم شما: ' + HZ.money(p.net || 0)));
    card.appendChild(money);
    var state;
    if (p.pay_state === 'disputed') state = 'اختلاف پرداخت ثبت شده است؛ هنوز تسویه نشده.';
    else if (!p.pay_state) state = 'منتظر انتخاب روش پرداخت توسط مسافر.';
    else if (p.confirmed) state = 'دریافت شما ثبت شد؛ منتظر تأیید مسافر.';
    else state = 'مسافر پرداخت نقدی را ثبت کرده. دریافت وجه را تأیید کنید.';
    card.appendChild(el('span', 'text-[11px] text-on-surface-variant', state));
    if (p.pay_method === 'cash' && p.pay_state === 'awaiting_cash' && !p.confirmed) {
      var row = el('div', 'flex flex-wrap gap-2');
      var ok = el('button', 'px-3 py-1.5 rounded-xl bg-[#006a61] text-white text-[11px] font-bold cursor-pointer', 'دریافت وجه را تأیید می‌کنم');
      ok.type = 'button';
      HZ_MISSION_ACTION.bind(ok, p.reservation_id);
      function payAction(action) {
        return HZ_MISSION_ACTION.run({ action: action, reservation_id: p.reservation_id, token: actor,
          total: p.total, net: p.net, refresh: function () { loadPayments(true); loadMissions(); } });
      }
      ok.onclick = function () { payAction('cash-confirm'); };
      var no = el('button', 'px-3 py-1.5 rounded-xl neu-raised text-error text-[11px] font-bold cursor-pointer', 'اختلاف دارم');
      no.type = 'button';
      HZ_MISSION_ACTION.bind(no, p.reservation_id);
      no.onclick = function () { payAction('cash-dispute'); };
      row.appendChild(ok); row.appendChild(no);
      card.appendChild(row);
    }
    return card;
  }
  // ---------- درخواست‌های زنده از سرور ----------
  function tok() { return HZ.load().token || null; }
  function srv(method, path) {
    var t = tok(); if (!t) return Promise.resolve({ status: 401, data: {} });
    return fetch('/api' + path, { method: method, headers: H.authHeaders(t, { 'Content-Type': 'application/json' }), body: arguments[2] !== undefined ? JSON.stringify(arguments[2]) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { status: r.status, data: d }; }); })
      .catch(function () { return { status: 0, data: {} }; });
  }

  // ---------- وضعیت زنده‌ی مدارک (فقط وضعیت؛ محتوا به مترجم نشان داده نمی‌شود) ----------
  var DOC_LABELS = { nid_card: 'کارت ملی', selfie: 'احراز چهره', portrait: 'عکس رسمی', address_proof: 'تأیید نشانی سکونت',
    criminal_record: 'گواهی عدم سوءپیشینه', drug_free: 'گواهی عدم اعتیاد', ipd_permit: 'مجوز ورود IPD',
    cip_permit: 'مجوز CIP', specialty_cert: 'مدرک تخصصی', car_docs: 'مدارک خودرو', licence: 'گواهینامه‌ی رانندگی' };
  function docStatusText(d) {
    if (d.expired) return { text: 'منقضی شده؛ مدرک جدید ارسال کنید', tone: 'text-error' };
    if (d.status === 'rejected') return { text: 'رد شده: ' + (d.reject_reason || 'بدون دلیل'), tone: 'text-error' };
    if (d.status === 'approved') return { text: d.expiring_soon ? 'تأیید شده؛ انقضا نزدیک است' : 'تأیید شده', tone: d.expiring_soon ? 'text-secondary' : 'text-primary' };
    return { text: 'در انتظار بررسی', tone: 'text-on-surface-variant' };
  }
  function renderLiveDocs() {
    var box = document.getElementById('live-docs-box'); if (!box) return;
    srv('GET', '/translator/documents').then(function (res) {
      if (res.status !== 200) return;
      box.textContent = '';
      var docs = res.data.documents || [];
      if (!docs.length) {
        var none = document.createElement('p'); none.className = 'text-[12px] text-on-surface-variant';
        none.textContent = 'هنوز مدرکی ارسال نشده است.'; box.appendChild(none); return;
      }
      docs.forEach(function (d) {
        var st = docStatusText(d);
        var row = document.createElement('div'); row.className = 'p-3 rounded-xl bg-surface-container-low flex justify-between gap-3 text-[12px]';
        var name = document.createElement('span'); name.className = 'font-bold text-on-surface'; name.textContent = DOC_LABELS[d.kind] || d.kind;
        var state = document.createElement('span'); state.className = 'font-bold ' + st.tone; state.textContent = st.text;
        row.appendChild(name); row.appendChild(state); box.appendChild(row);
      });
    });
  }
  // چهار بُعد صلاحیت از سرور (نه متن ثابت)
  function renderCapability() {
    var box = document.getElementById('cap-box'); if (!box) return;
    srv('GET', '/translator/capability').then(function (res) {
      if (res.status !== 200 || !res.data.dimensions) return;
      var dm = res.data.dimensions;
      var medicalPermit = !dm.medical || typeof dm.medical.permit_required !== 'boolean'
        ? { ok: false, text: 'وضعیت نامشخص' }
        : dm.medical.permit_required === false
          ? { ok: false, text: 'ارائهٔ مجوز پزشکی در این نسخه الزامی نیست' }
          : typeof dm.medical.ok !== 'boolean'
            ? { ok: false, text: 'وضعیت نامشخص' }
            : { ok: dm.medical.ok, text: dm.medical.ok ? 'مدرک تأیید شده' : 'مدرک تأیید نشده' };
      var rows = [
        ['احراز هویت و صلاحیت امنیتی', dm.identity.ok, dm.identity.ok ? 'کامل و تأیید شده' : 'کمبود: ' + dm.identity.missing.map(function (k) { return DOC_LABELS[k] || k; }).join('، ')],
        ['آزمون زبان', dm.language.ok, dm.language.ok ? 'جفت‌زبان ثبت شده: ' + dm.language.langs.join('، ') : 'هنوز تکمیل نشده'],
        ['خودرو و بیمه‌نامه', dm.car.active, dm.car.active ? 'فعال' : (dm.car.registered ? 'غیرفعال (مدارک تأییدشده یا معتبر نیست)' : 'ثبت نشده (اختیاری)')],
        ['مدرک پزشکی (IPD)', medicalPermit.ok, medicalPermit.text]
      ];
      box.textContent = '';
      rows.forEach(function (r) {
        var row = document.createElement('div'); row.className = 'p-3 rounded-xl bg-surface-container-low flex justify-between gap-3 text-[12px]';
        var name = document.createElement('span'); name.className = 'font-bold text-on-surface'; name.textContent = r[0];
        var state = document.createElement('span'); state.className = 'font-bold ' + (r[1] ? 'text-primary' : 'text-on-surface-variant'); state.textContent = r[2];
        row.appendChild(name); row.appendChild(state); box.appendChild(row);
      });
    });
  }
  // یادآوری‌های انقضا (سند ۷: ۳۰ روز قبل و پس از انقضا)
  function renderNotifications() {
    var box = document.getElementById('notif-box'); if (!box) return;
    srv('GET', '/translator/notifications').then(function (res) {
      if (res.status !== 200) return;
      box.textContent = '';
      (res.data.notifications || []).slice(0, 5).forEach(function (n) {
        var row = document.createElement('div');
        row.className = 'p-3 rounded-xl bg-secondary-fixed/40 text-[12px] text-secondary font-bold';
        row.textContent = (n.doc_name ? n.doc_name + ': ' : '') + n.text;
        box.appendChild(row);
      });
    });
  }
  // نوبت مصاحبه‌ی زنده (سند ۵): فقط زمان‌های آزاد واقعی؛ یادداشت هماهنگی از سوی مدیر
  function ivFmt(iso) {
    var txt = new Date(iso).toLocaleString('en-GB', { timeZone: 'Asia/Tehran', hour: '2-digit', minute: '2-digit', hour12: false, day: 'numeric', month: 'short' });
    return txt.replace(/\d/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[d]; });
  }
  function renderInterview() {
    var box = document.getElementById('iv-box'); if (!box) return;
    srv('GET', '/translator/interview-slots').then(function (res) {
      if (res.status !== 200) return;
      box.textContent = '';
      var card = document.createElement('div');
      card.className = 'p-4 rounded-xl bg-surface-container-lowest border border-outline-variant/40 flex flex-col gap-2';
      var title = document.createElement('div');
      title.className = 'font-bold text-on-surface'; title.textContent = 'مصاحبه‌ی زبان (۱۰ دقیقه‌ی زنده)';
      card.appendChild(title);
      var msg = document.createElement('div');
      msg.className = 'text-[12px] text-on-surface-variant';
      card.appendChild(msg);
      var action = document.createElement('div');
      action.className = 'flex flex-wrap gap-2';
      card.appendChild(action);
      if (res.data.booking) {
        // هماهنگی مصاحبه (حضوری یا ابزار بیرونی) از سوی مدیر اعلام می‌شود؛ اتاق ویدئویی نداریم
        var note = res.data.booking.note ? ' — ' + res.data.booking.note : '';
        msg.textContent = 'نوبت شما: ' + ivFmt(res.data.booking.starts_at) + note;
      } else {
        var slots = res.data.slots || [];
        msg.textContent = slots.length ? 'یک نوبت آزاد انتخاب کنید.' : 'فعلاً نوبت آزادی نیست.';
        slots.slice(0, 3).forEach(function (sl) {
          var b = document.createElement('button');
          b.type = 'button'; b.className = 'px-3 py-2 rounded-xl border border-primary text-primary text-[12px] font-bold';
          b.textContent = ivFmt(sl.starts_at);
          b.onclick = function () {
            srv('POST', '/translator/interview-slots/' + sl.id + '/book').then(function (r) {
              if (r.status === 200) renderInterview();
              else msg.textContent = 'رزرو انجام نشد: ' + (r.data.error === 'slot_taken' ? 'این نوبت پر شده است' : (r.data.error === 'languages_required' ? 'ابتدا زبان انتخاب کنید' : 'خطا'));
            });
          };
          action.appendChild(b);
        });
      }
      box.appendChild(card);
    });
  }
  renderLiveDocs(); renderCapability(); renderNotifications(); renderInterview();
  setInterval(function () { renderLiveDocs(); renderCapability(); renderNotifications(); renderInterview(); }, 30000);

  var offersBox = document.getElementById('offers-box');
  var lastOffers = [];
  var lastChanges = [];
  var lastExtensions = [];
  function updateWorkspaceSheetSummary() {
    var label = document.getElementById('workspace-sheet-state');
    var meta = document.getElementById('workspace-sheet-meta');
    var dot = document.getElementById('workspace-sheet-state-dot');
    if (!label || !meta || !dot) return;

    var stateText = 'در انتظار درخواست تازه';
    var metaText = 'فاصله و زمان مسیر نمایش داده نمی‌شود';
    var tone = 'is-idle';
    var offer = Array.isArray(lastOffers) && lastOffers.length ? lastOffers[0] : null;
    var extension = Array.isArray(lastExtensions) && lastExtensions.length ? lastExtensions[0] : null;
    var change = Array.isArray(lastChanges) && lastChanges.length ? lastChanges[0] : null;
    var pendingResponse = offer || extension || change;
    if (pendingResponse) {
      stateText = offer ? (offer.kind === 'scheduled' ? 'پیشنهاد زمان‌دار' : 'پیشنهاد فوری')
        : extension ? 'درخواست تمدید خدمت' : 'درخواست تغییر مأموریت';
      metaText = 'فرصت پاسخ: ' + HZ.toFa(Math.max(0, Math.ceil((Date.parse(pendingResponse.expires_at) - Date.now()) / 1000))) + ' ثانیه';
      tone = 'is-offer';
      meta.setAttribute('data-exp', pendingResponse.expires_at);
      meta.setAttribute('data-offer-timer', '1');
    } else {
      meta.removeAttribute('data-exp');
      meta.removeAttribute('data-offer-timer');
      if (MISSIONS.length) {
        var mappedMission = MISSIONS.find(hasMissionCoordinates);
        stateText = 'مأموریت پذیرفته‌شده';
        metaText = mappedMission ? 'نقطهٔ ملاقات ثبت‌شده روی نقشه' : 'مختصات واقعی از سرور موجود نیست';
        tone = 'is-accepted';
      } else if (missionsState === 'nosession') {
        stateText = 'ورود به حساب لازم است';
        metaText = 'اطلاعات مأموریت از سرور دریافت نمی‌شود';
        tone = 'is-error';
      } else if (offersState === 'error' || missionsState === 'error') {
        stateText = 'درخواست‌ها دریافت نشدند';
        metaText = 'برای تلاش دوباره، دریافت را بررسی کنید';
        tone = 'is-error';
      } else if (offersState === 'loading' || missionsState === 'loading') {
        stateText = 'در حال بررسی درخواست‌ها';
        metaText = 'وضعیت واقعی از سرور دریافت می‌شود';
        tone = 'is-loading';
      }
    }
    label.textContent = stateText;
    meta.textContent = metaText;
    dot.className = 'translator-sheet-state-dot ' + tone;
  }
  function syncWorkspaceEmptyMissions() {
    var box = document.getElementById('missions-list');
    if (!box || MISSIONS.length || missionsState !== 'ok') return;
    var pending = lastOffers.length || lastChanges.length || lastExtensions.length;
    var emptyCard = box.querySelector('.translator-empty-missions');
    if (pending && emptyCard) emptyCard.remove();
    if (!pending && !emptyCard) {
      box.innerHTML = '';
      box.appendChild(el('div', 'translator-empty-missions', 'فعلاً مأموریت پذیرفته‌شده‌ای ندارید. درخواست‌های جدید بعد از تأیید پذیرفته می‌شوند.'));
    }
  }
  var CHANGE_LABEL = { notes: 'یادداشت', scheduled_at: 'زمان', place: 'محل ملاقات', origin_lang: 'زبان مبدأ', dest_lang: 'زبان مقصد', field: 'حوزه', hours: 'مدت', car: 'خودرو', party: 'تعداد همراه', gender_pref: 'ترجیح جنسیت' };
  function renderChange(c) {
    var actor = tok();
    var card = el('div', 'translator-change-card rounded-2xl bg-surface p-4 sm:p-5 neu-raised flex flex-col gap-3 border border-secondary/40');
    card.setAttribute('data-change-id', c.id);
    card.appendChild(el('span', 'text-[13px] font-bold text-on-surface', 'درخواست تغییر ماموریت'));
    var parts = Object.keys(c.changes).filter(function (k) { return CHANGE_LABEL[k]; }).map(function (k) {
      var v = c.changes[k];
      if (k === 'scheduled_at') v = HZ.jDate(new Date(v)) + ' ' + HZ.clock(new Date(v));
      return CHANGE_LABEL[k] + ': ' + v;
    });
    card.appendChild(el('span', 'text-[11px] text-on-surface-variant', parts.join(' • ') || 'تغییر جزئی'));
    var row = el('div', 'flex items-center justify-between gap-2 pt-2 border-t border-surface-variant/40 text-[12px]');
    var tm = el('span', 'font-bold text-secondary', HZ.toFa(Math.max(0, Math.ceil((Date.parse(c.expires_at) - Date.now()) / 1000))) + ' ثانیه');
    tm.setAttribute('data-exp', c.expires_at); tm.setAttribute('data-pure', '1');
    row.appendChild(tm);
    var btns = el('div', 'flex gap-2');
    var no = el('button', 'px-4 py-2 rounded-xl neu-raised text-[12px] font-bold text-on-surface cursor-pointer', 'رد');
    no.type = 'button';
    HZ_MISSION_ACTION.bind(no, c.reservation_id);
    function decideChange(action) {
      return HZ_MISSION_ACTION.run({ action: action, id: c.id, reservation_id: c.reservation_id, changes: c.changes, token: actor,
        refresh: function () { loadMissions(); refreshOffers(true); } });
    }
    no.onclick = function () { decideChange('change-reject'); };
    var yes = el('button', 'px-4 py-2 rounded-xl bg-[#006a61] text-white text-[12px] font-bold cursor-pointer', 'پذیرش');
    yes.type = 'button';
    HZ_MISSION_ACTION.bind(yes, c.reservation_id);
    yes.onclick = function () { decideChange('change-accept'); };
    btns.appendChild(no); btns.appendChild(yes); row.appendChild(btns);
    card.appendChild(row);
    return card;
  }
  function renderExtension(e) {
    var actor = tok();
    var card = el('div', 'translator-extension-card rounded-2xl bg-surface p-4 sm:p-5 neu-raised flex flex-col gap-3 border border-amber-500/50');
    card.appendChild(el('span', 'text-[13px] font-bold text-on-surface', 'درخواست تمدید خدمت'));
    var details = [];
    if (e.traveler_name) details.push('مسافر: ' + e.traveler_name);
    if (e.place) details.push('محل ملاقات: ' + e.place);
    details.push('تمدید ' + HZ.toFa(e.extra_hours) + ' ساعت');
    details.push('سهم شما پس از تمدید: ' + HZ.money(e.new_net));
    card.appendChild(el('span', 'text-[11px] text-on-surface-variant', details.join(' • ')));
    var row = el('div', 'flex items-center justify-between gap-2 pt-2 border-t border-surface-variant/40 text-[12px]');
    var tm = el('span', 'font-bold text-secondary', HZ.toFa(Math.max(0, Math.ceil((Date.parse(e.expires_at) - Date.now()) / 1000))) + ' ثانیه');
    tm.setAttribute('data-exp', e.expires_at); tm.setAttribute('data-pure', '1');
    row.appendChild(tm);
    var btns = el('div', 'flex gap-2');
    var no = el('button', 'px-4 py-2 rounded-xl neu-raised text-[12px] font-bold text-on-surface cursor-pointer', 'رد');
    no.type = 'button';
    HZ_MISSION_ACTION.bind(no, e.reservation_id);
    no.onclick = function () { serviceAction('reject', e, undefined, actor); };
    var yes = el('button', 'px-4 py-2 rounded-xl bg-[#006a61] text-white text-[12px] font-bold cursor-pointer', 'پذیرش');
    yes.type = 'button';
    HZ_MISSION_ACTION.bind(yes, e.reservation_id);
    yes.onclick = function () { serviceAction('accept', e, undefined, actor); };
    btns.appendChild(no); btns.appendChild(yes); row.appendChild(btns);
    card.appendChild(row);
    return card;
  }
  var FIELD_LABEL_FA = { general: 'عمومی', medical: 'پزشکی', legal: 'حقوقی', business: 'تجاری' };
  var LANGUAGE_LABEL_FA = { fa: 'فارسی', ar: 'عربی', en: 'انگلیسی', tr: 'ترکی', fr: 'فرانسوی', ru: 'روسی', zh: 'چینی' };
  function renderOffers() {
    if (!offersBox) return;
    offersBox.innerHTML = '';
    if (offersState === 'error') {
      var errorCard = el('div', 'translator-offer-card translator-request-error');
      var errorPrimary = el('div', 'translator-offer-primary');
      var errorSummary = el('div', 'translator-offer-summary');
      errorSummary.appendChild(el('strong', 'translator-offer-traveler', 'دریافت درخواست‌ها انجام نشد'));
      var errorState = el('div', 'translator-offer-state-line');
      errorState.appendChild(el('span', 'translator-offer-state-title', 'اتصال به سرور را بررسی کنید'));
      errorSummary.appendChild(errorState);
      errorPrimary.appendChild(errorSummary);
      var errorIcon = el('div', 'translator-offer-countdown translator-offer-error-icon');
      errorIcon.appendChild(el('span', 'material-symbols-outlined', 'sync_problem'));
      errorPrimary.appendChild(errorIcon);
      errorCard.appendChild(errorPrimary);
      var errorNote = el('div', 'translator-offer-notes');
      errorNote.appendChild(el('span', 'material-symbols-outlined translator-offer-note-icon', 'info'));
      errorNote.appendChild(el('strong', 'translator-offer-error-copy', 'برای دریافت دوباره تلاش کنید. دادهٔ مأموریت یا محل ساختگی نمایش داده نمی‌شود.'));
      errorCard.appendChild(errorNote);
      var retry = el('button', 'translator-offer-retry neu-flat', 'تلاش دوباره');
      retry.type = 'button'; retry.onclick = function () { refreshOffers(true); }; errorCard.appendChild(retry);
      offersBox.appendChild(errorCard);
      updateTranslatorMap();
      updateWorkspaceSheetSummary();
      syncWorkspaceEmptyMissions();
      return;
    }
    lastExtensions.forEach(function (e) { offersBox.appendChild(renderExtension(e)); });
    lastChanges.forEach(function (c) { offersBox.appendChild(renderChange(c)); });
    if (offersState === 'ok' && !lastExtensions.length && !lastChanges.length && !lastOffers.length) {
      offersBox.appendChild(el('div', 'translator-empty-offers', 'در حال حاضر پیشنهاد یا درخواست تغییری برای پاسخ ثبت نشده است.'));
    }
    lastOffers.forEach(function (o) {
      var card = el('div', 'translator-offer-card');
      var actor = tok();
      card.setAttribute('data-offer-id', o.id);

      var kind = o.kind === 'scheduled' ? 'درخواست زمان‌دار' : 'درخواست فوری';
      var primary = el('div', 'translator-offer-primary');
      var summary = el('div', 'translator-offer-summary');
      summary.appendChild(el('strong', 'translator-offer-traveler', o.traveler_name || 'نام مسافر اعلام نشده'));
      var stateLine = el('div', 'translator-offer-state-line');
      stateLine.appendChild(el('span', 'translator-offer-state-title', 'پیشنهاد جدید منتظر بررسی'));
      stateLine.appendChild(el('span', 'translator-offer-state-dot'));
      stateLine.appendChild(el('span', 'translator-offer-kind', kind));
      summary.appendChild(stateLine);
      primary.appendChild(summary);

      var remaining = Math.max(0, Math.ceil((Date.parse(o.expires_at) - Date.now()) / 1000));
      var timer = el('div', 'translator-offer-countdown');
      timer.setAttribute('role', 'timer');
      timer.setAttribute('aria-label', 'فرصت پاسخ به پیشنهاد');
      var ring = el('span', 'translator-offer-countdown-ring');
      var count = el('span', 'translator-offer-countdown-value', HZ.toFa(remaining));
      count.setAttribute('data-exp', o.expires_at);
      count.setAttribute('data-countdown-ring', '1');
      ring.appendChild(count);
      timer.appendChild(ring);
      primary.appendChild(timer);

      var compensation = el('div', 'translator-offer-compensation');
      compensation.appendChild(el('small', '', 'سهم مترجم'));
      compensation.appendChild(el('strong', '', HZ.money(o.net || 0)));
      compensation.appendChild(el('small', 'translator-offer-currency', 'تومان'));
      primary.appendChild(compensation);
      card.appendChild(primary);

      var facts = el('div', 'translator-offer-facts');
      function offerFact(icon, label, value, extraClass) {
        if (!value) return;
        var fact = el('div', 'translator-offer-fact');
        fact.appendChild(el('span', 'material-symbols-outlined translator-offer-fact-icon', icon));
        var copy = el('div', 'translator-offer-fact-copy');
        copy.appendChild(el('small', '', label));
        copy.appendChild(el('strong', extraClass || '', value));
        fact.appendChild(copy);
        facts.appendChild(fact);
      }
      if (o.origin_lang && o.dest_lang) {
        offerFact('translate', 'خدمت زبانی',
          (LANGUAGE_LABEL_FA[o.origin_lang] || o.origin_lang) + ' ← ' + (LANGUAGE_LABEL_FA[o.dest_lang] || o.dest_lang));
      }
      if (o.field) offerFact('work', 'حوزهٔ خدمت', FIELD_LABEL_FA[o.field] || o.field);
      offerFact('place', 'محل ملاقات', o.place || 'نشانی در درخواست ثبت نشده');
      if (o.kind === 'scheduled' && o.scheduled_at) {
        var scheduled = new Date(o.scheduled_at);
        offerFact('calendar_month', 'زمان قرار', HZ.jDate(scheduled) + '، ساعت ' + HZ.clock(scheduled));
      } else {
        offerFact('bolt', 'زمان درخواست', 'فوری');
      }
      card.appendChild(facts);

      if (o.notes) {
        var note = el('div', 'translator-offer-notes');
        note.appendChild(el('span', 'material-symbols-outlined translator-offer-note-icon', 'format_quote'));
        var noteCopy = el('div', 'translator-offer-note-copy');
        noteCopy.appendChild(el('small', '', 'یادداشت مسافر'));
        noteCopy.appendChild(el('strong', '', '«' + o.notes + '»'));
        note.appendChild(noteCopy);
        card.appendChild(note);
      }

      var btns = el('div', 'translator-offer-actions');
      var no = el('button', 'translator-offer-reject', 'رد');
      no.type = 'button';
      HZ_MISSION_ACTION.bind(no, o.reservation_id);
      function decideOffer(action) {
        return HZ_MISSION_ACTION.run({ action: action, id: o.id, reservation_id: o.reservation_id, net: o.net, token: actor,
          refresh: function () { loadMissions(); refreshOffers(true); } });
      }
      no.onclick = function () { decideOffer('offer-decline'); };
      var yes = el('button', 'translator-offer-accept', 'پذیرش');
      yes.type = 'button';
      HZ_MISSION_ACTION.bind(yes, o.reservation_id);
      yes.onclick = function () { decideOffer('offer-accept'); };
      btns.appendChild(no);
      btns.appendChild(yes);
      card.appendChild(btns);
      offersBox.appendChild(card);
    });
    updateTranslatorMap();
    updateWorkspaceSheetSummary();
    syncWorkspaceEmptyMissions();
  }
  var offersSig = '', offersState = 'loading';
  var offerRead = 0, offerApplied = 0, offerRevision = 0;
  function refreshOffers(invalidate) {
    var token = tok(), read = ++offerRead, revision = invalidate ? ++offerRevision : offerRevision;
    if (!token) return;
    srv('GET', '/translator/offers').then(function (res) {
      if (tok() !== token || revision !== offerRevision || read < offerApplied) return;
      if (res.status !== 200 || !res.data || !Array.isArray(res.data.offers) || !Array.isArray(res.data.changes) || !Array.isArray(res.data.extensions) ||
          !res.data.changes.every(function (c) { return c && Number.isSafeInteger(c.id) && c.id > 0 && Number.isSafeInteger(c.reservation_id) && c.reservation_id > 0 &&
            typeof c.expires_at === 'string' && Number.isFinite(Date.parse(c.expires_at)) && HZ_MISSION_ACTION.validChanges(c.changes); }) ||
          !res.data.extensions.every(function (e) { return e && Number.isSafeInteger(e.id) && e.id > 0 && Number.isSafeInteger(e.reservation_id) && e.reservation_id > 0 &&
            Number.isInteger(e.extra_hours) && e.extra_hours >= 1 && e.extra_hours <= 4 && typeof e.extra_net === 'number' && Number.isFinite(e.extra_net) && e.extra_net >= 0 &&
            typeof e.new_net === 'number' && Number.isFinite(e.new_net) && e.new_net >= 0 && typeof e.expires_at === 'string' && Number.isFinite(Date.parse(e.expires_at)) &&
            (e.traveler_name == null || typeof e.traveler_name === 'string') && (e.place == null || typeof e.place === 'string'); }) ||
          !res.data.offers.every(function (o) { return o && Number.isSafeInteger(o.id) && o.id > 0 && Number.isSafeInteger(o.reservation_id) && o.reservation_id > 0 &&
            ['instant', 'scheduled'].includes(o.kind) && typeof o.expires_at === 'string' && Number.isFinite(Date.parse(o.expires_at)) && typeof o.net === 'number' && Number.isFinite(o.net) && o.net >= 0 &&
            (o.kind !== 'scheduled' || (typeof o.scheduled_at === 'string' && Number.isFinite(Date.parse(o.scheduled_at)))) &&
            (o.traveler_name == null || typeof o.traveler_name === 'string') && (o.place == null || typeof o.place === 'string') &&
            (o.notes == null || typeof o.notes === 'string'); }) ||
          new Set(res.data.offers.map(function (o) { return o.id; })).size !== res.data.offers.length) {
        offerApplied = read; offersState = 'error'; offersSig = ''; lastOffers = []; lastChanges = []; lastExtensions = []; renderOffers(); return;
      }
      offersState = 'ok';
      offerApplied = read;
      lastOffers = res.data.offers;
      lastChanges = res.data.changes;
      lastExtensions = res.data.extensions;
      // Quote changes as well as IDs invalidate cards. Re-rendered controls
      // inherit the reservation lock, never silently unlocking an action.
      var sig = JSON.stringify([lastOffers, lastChanges, lastExtensions]);
      if (sig !== offersSig) { offersSig = sig; renderOffers(); }
      HZ_MISSION_ACTION.update();
    });
  }
  setInterval(refreshOffers, 3000);
  loadPayments(); setInterval(loadPayments, 5000);
  // شمارش معکوس هر ثانیه، بدون بازسازی کارت‌ها
  setInterval(function () {
    document.querySelectorAll('[data-exp]').forEach(function (t) {
      var left = Math.max(0, Math.ceil((Date.parse(t.getAttribute('data-exp')) - Date.now()) / 1000));
      if (t.getAttribute('data-countdown-ring')) t.textContent = HZ.toFa(left);
      else if (t.getAttribute('data-pure')) t.textContent = HZ.toFa(left) + ' ثانیه';
      else if (t.getAttribute('data-offer-timer')) t.textContent = 'فرصت پاسخ: ' + HZ.toFa(left) + ' ثانیه';
      else t.textContent = t.textContent.replace(/• .*ثانیه$/, '• ' + HZ.toFa(left) + ' ثانیه');
    });
  }, 1000);
  refreshOffers(true);

  loadMissions();
  setInterval(loadMissions, 5000);
  setInterval(updateServiceTimers, 1000);

  var p = state.profile || {};
  var displayName = [p.nameFa, p.lastFa].filter(Boolean).join(' ') || 'مترجم';

  // نام نمایشی از دادهٔ محلی در سرایند و کارت‌ها می‌آید؛ این داده به‌تنهایی هویت سروری را ثابت نمی‌کند.
  function applyDisplayName() {
    document.querySelectorAll('[data-tr-name]').forEach(function (el) { el.textContent = displayName; });
  }

  applyDisplayName();
  window.addEventListener('DOMContentLoaded', applyDisplayName);
})();
