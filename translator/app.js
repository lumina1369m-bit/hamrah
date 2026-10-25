
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
            (m.arrived_at === null || typeof m.arrived_at === 'string' && Number.isFinite(Date.parse(m.arrived_at))) &&
            ['instant', 'scheduled'].includes(m.kind) && ['fa', 'ar', 'en', 'tr', 'fr', 'ru', 'zh'].includes(m.origin_lang) &&
            ['fa', 'ar', 'en', 'tr', 'fr', 'ru', 'zh'].includes(m.dest_lang) && (m.car === 0 || m.car === 1) &&
            Number.isInteger(m.party) && m.party >= 1 && m.party <= 20 && typeof m.notes === 'string' &&
            (m.scheduled_at === null || typeof m.scheduled_at === 'string' && Number.isFinite(Date.parse(m.scheduled_at))) &&
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
        var signature = JSON.stringify([nextMissions, nextMissions.map(function (m) {
          return !!m.scheduled_at && Date.parse(m.scheduled_at) > serverTime;
        })]);
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
      id: m.id, code: code, token: actor, serverTimeOffset: offerServerClockOffset, refresh: function () { loadMissions(); refreshOffers(true); } });
  }
  var extensionModalContext = null, finishModalContext = null, cashModalContext = null, modalReturnFocus = null;
  function showMissionModal(id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    modalReturnFocus = document.activeElement;
    modal.hidden = false; modal.setAttribute('aria-hidden', 'false');
    var dialog = modal.querySelector('[role="dialog"]');
    if (dialog) dialog.focus();
  }
  function hideMissionModal(id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    modal.hidden = true; modal.setAttribute('aria-hidden', 'true');
    if (modalReturnFocus && typeof modalReturnFocus.focus === 'function') modalReturnFocus.focus();
    modalReturnFocus = null;
  }
  document.querySelectorAll('.translator-action-modal').forEach(function (modal) {
    modal.addEventListener('click', function (event) {
      if (event.target === modal) hideMissionModal(modal.id);
      var close = event.target.closest && event.target.closest('[data-modal-close]');
      if (close) hideMissionModal(modal.id);
    });
  });
  document.addEventListener('keydown', function (event) {
    var visible = document.querySelector('.translator-action-modal:not([hidden])');
    if (!visible) return;
    if (event.key === 'Escape') { hideMissionModal(visible.id); return; }
    if (event.key !== 'Tab') return;
    var controls = visible.querySelectorAll('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])');
    if (!controls.length) { event.preventDefault(); visible.querySelector('[role="dialog"]').focus(); return; }
    var first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  function openExtensionModal(e, source) {
    if (!e || !Number.isSafeInteger(e.id) || !Number.isSafeInteger(e.reservation_id)) return;
    extensionModalContext = { request: e, token: tok() };
    var traveler = e.traveler_name || 'مسافر';
    document.getElementById('mission-extension-copy').textContent = traveler + ' درخواست ' + HZ.toFa(e.extra_hours) + ' ساعت تمدید خدمت را ثبت کرده است.';
    document.getElementById('mission-extension-hours').textContent = '+' + HZ.toFa(e.extra_hours) + ' ساعت';
    document.getElementById('mission-extension-extra').textContent = HZ.money(e.extra_total) + ' تومان';
    document.getElementById('mission-extension-net').textContent = HZ.money(e.new_net) + ' تومان';
    var expiry = document.getElementById('mission-extension-expiry');
    expiry.textContent = HZ.toFa(Math.max(0, Math.ceil((Date.parse(e.expires_at) - (Date.now() + offerServerClockOffset)) / 1000))) + ' ثانیه';
    expiry.setAttribute('data-exp', e.expires_at); expiry.setAttribute('data-pure', '1'); expiry.setAttribute('data-offer-timer', '1');
    var accept = document.getElementById('mission-extension-accept');
    var reject = document.getElementById('mission-extension-reject');
    HZ_MISSION_ACTION.bind(accept, e.reservation_id); HZ_MISSION_ACTION.bind(reject, e.reservation_id);
    accept.onclick = function () {
      var context = extensionModalContext; hideMissionModal('mission-extension-modal');
      if (context && context.token) serviceAction('accept', context.request, undefined, context.token);
    };
    reject.onclick = function () {
      var context = extensionModalContext; hideMissionModal('mission-extension-modal');
      if (context && context.token) serviceAction('reject', context.request, undefined, context.token);
    };
    if (source) modalReturnFocus = source;
    showMissionModal('mission-extension-modal');
  }
  function openFinishModal(m, source) {
    if (!m || !Number.isSafeInteger(m.reservation_id)) return;
    finishModalContext = { mission: m, token: tok() };
    document.getElementById('mission-finish-hours').textContent = HZ.toFa(m.hours) + ' ساعت';
    document.getElementById('mission-finish-total').textContent = HZ.money(m.total) + ' تومان';
    document.getElementById('mission-finish-net').textContent = HZ.money(m.net) + ' تومان';
    var button = document.getElementById('mission-finish-confirm');
    HZ_MISSION_ACTION.bind(button, m.reservation_id);
    button.onclick = function () {
      var context = finishModalContext; hideMissionModal('mission-finish-modal');
      if (context && context.token) serviceAction('finish', context.mission, undefined, context.token);
    };
    if (source) modalReturnFocus = source;
    showMissionModal('mission-finish-modal');
  }
  function openCashModal(p, source) {
    var token = tok();
    if (!p || !Number.isSafeInteger(p.reservation_id)) return;
    if (!token || paymentOwnerToken !== token) {
      paymentOwnerToken = null; PAYMENTS_LIST = []; SETTLEMENTS_LIST = [];
      paymentsState = token ? 'loading' : 'error'; renderPayments();
      if (token) loadPayments(true);
      return;
    }
    cashModalContext = { payment: p, token: token };
    document.getElementById('mission-cash-copy').textContent = p.confirmed
      ? 'دریافت وجه شما ثبت شده است؛ منتظر تأیید نهایی مسافر هستید.'
      : 'مسافر دریافت نقدی را ثبت کرده است. فقط اگر وجه کامل را واقعاً دریافت کرده‌اید، تأیید کنید.';
    document.getElementById('mission-cash-total').textContent = HZ.money(p.total) + ' تومان';
    document.getElementById('mission-cash-net').textContent = HZ.money(p.net) + ' تومان';
    var confirm = document.getElementById('mission-cash-confirm');
    var dispute = document.getElementById('mission-cash-dispute');
    HZ_MISSION_ACTION.bind(confirm, p.reservation_id); HZ_MISSION_ACTION.bind(dispute, p.reservation_id);
    function decide(action) {
      var context = cashModalContext; hideMissionModal('mission-cash-modal');
      if (!context || !context.token) return;
      HZ_MISSION_ACTION.run({ action: action, reservation_id: context.payment.reservation_id, token: context.token,
        total: context.payment.total, net: context.payment.net, refresh: function () { loadPayments(true); loadMissions(); } });
    }
    confirm.onclick = function () { decide('cash-confirm'); };
    dispute.onclick = function () { decide('cash-dispute'); };
    if (source) modalReturnFocus = source;
    showMissionModal('mission-cash-modal');
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
      var remaining = Math.max(0, planned - elapsed);
      var text = elapsed >= planned
        ? 'مدت توافق‌شده سپری شده؛ پایان خدمت به تأیید مسافر نیاز دارد.'
        : 'باقی‌ماندهٔ قرارداد: ' + serviceDuration(remaining);
      timer.textContent = text;
      timer.setAttribute('aria-label', text + '؛ زمان سپری‌شده ' + serviceDuration(elapsed));
    });
  }
  function missionCard(m) {
    var actor = tok();
    var card = el('article', 'translator-mission-card');
    card.setAttribute('data-mission-reservation', m.reservation_id);
    var FIELD_FA = { general: 'عمومی', medical: 'پزشکی', legal: 'حقوقی', business: 'تجاری' };
    var LANG_FA = LANGUAGE_LABEL_FA || { fa: 'فارسی', ar: 'عربی', en: 'انگلیسی', tr: 'ترکی', fr: 'فرانسوی', ru: 'روسی', zh: 'چینی' };
    var primary = el('div', 'translator-offer-primary');
    var summary = el('div', 'translator-offer-summary');
    var futureAppointment = !!m.scheduled_at && Date.parse(m.scheduled_at) > Date.now() + serverClockOffset;
    summary.appendChild(el('strong', 'translator-offer-traveler', m.travelerName || 'نام مسافر اعلام نشده'));
    var stateLine = el('div', 'translator-offer-state-line');
    var stateTitle = m.finish_requested ? 'درخواست پایان فرستاده شده'
      : m.started ? 'همراهی و ترجمه همزمان در حال اجرا'
      : futureAppointment ? (m.arrived_at ? 'حضور ثبت‌شده • منتظر موعد' : 'مأموریت زمان‌دار • منتظر موعد')
      : m.arrived_at ? 'حضور در محل • دریافت کد مسافر'
      : 'پذیرفته شد • آمادهٔ اعزام';
    stateLine.appendChild(el('span', 'translator-offer-state-title', stateTitle));
    stateLine.appendChild(el('span', 'translator-offer-state-dot', ''));
    stateLine.appendChild(el('span', 'translator-offer-kind', m.kind === 'scheduled' ? 'مأموریت زمان‌دار' : 'مأموریت فوری'));
    summary.appendChild(stateLine);
    var sub = m.finish_requested ? 'منتظر تأیید یا ثبت پایان توسط مسافر'
      : m.started ? 'زمان خدمت فقط از ثبت واقعی سرور محاسبه می‌شود'
      : futureAppointment ? (m.arrived_at ? 'شروع پس از زمان قرار فعال می‌شود' : 'ثبت حضور پس از زمان قرار فعال می‌شود')
      : m.arrived_at ? 'کد ۵ رقمی را از مسافر بخواهید؛ کد در صفحه نمایش داده نمی‌شود'
      : 'محل دقیق پس از پذیرش، فقط با مختصات معتبر سرور روی نقشه نشان داده می‌شود';
    summary.appendChild(el('small', 'translator-offer-kind-detail', sub));
    if (m.kind === 'scheduled' && m.scheduled_at) {
      var scheduled = new Date(m.scheduled_at);
      summary.appendChild(el('small', 'translator-offer-kind-detail', HZ.jDate(scheduled) + ' • ' + HZ.clock(scheduled)));
    }
    primary.appendChild(summary);

    var stateIcon = el('div', 'translator-offer-countdown translator-mission-state-icon');
    var iconName = m.finish_requested ? 'hourglass_top' : m.started ? 'record_voice_over' : futureAppointment ? 'schedule' : m.arrived_at ? 'pin' : 'directions_run';
    stateIcon.appendChild(el('span', 'material-symbols-outlined', iconName));
    primary.appendChild(stateIcon);

    var compensation = el('div', 'translator-offer-compensation');
    compensation.appendChild(el('small', '', 'حق‌الزحمه تعهد (' + HZ.toFa(m.hours) + ' ساعت)'));
    compensation.appendChild(el('strong', '', HZ.money(m.net)));
    compensation.appendChild(el('small', 'translator-offer-currency', 'سهم خالص مترجم'));
    compensation.appendChild(el('small', 'translator-offer-currency', 'مبلغ کل: ' + HZ.money(m.total) + ' تومان'));
    primary.appendChild(compensation);
    card.appendChild(primary);

    // Code6 keeps secure contact actions in accepted states; the real service is not available, so controls stay explicitly disabled.
    if (m.status === 'matched' || m.status === 'accepted') {
      var unavailable = el('div', 'translator-secure-communication');
      [['call', 'تماس امن صوتی'], ['chat', 'پیام‌رسان درون‌برنامه‌ای']].forEach(function (entry) {
        var disabledAction = el('button', 'translator-secure-unavailable');
        disabledAction.type = 'button'; disabledAction.disabled = true;
        disabledAction.appendChild(el('span', 'material-symbols-outlined', entry[0]));
        var copy = el('span', 'translator-secure-unavailable-copy');
        copy.appendChild(el('strong', '', entry[1]));
        copy.appendChild(el('small', '', 'در دسترس نیست'));
        disabledAction.appendChild(copy);
        unavailable.appendChild(disabledAction);
      });
      card.appendChild(unavailable);
    }

    var facts = el('div', 'translator-offer-facts');
    function missionFact(icon, label, value) {
      var fact = el('div', 'translator-offer-fact');
      fact.appendChild(el('span', 'material-symbols-outlined translator-offer-fact-icon', icon));
      var copy = el('div', 'translator-offer-fact-copy');
      copy.appendChild(el('small', '', label));
      copy.appendChild(el('strong', '', value));
      fact.appendChild(copy); facts.appendChild(fact);
    }
    var language = (LANG_FA[m.origin_lang] || m.origin_lang) + ' ⟷ ' + (LANG_FA[m.dest_lang] || m.dest_lang);
    if (m.purpose && m.purpose !== 'general') language += ' • ' + (FIELD_FA[m.purpose] || m.purpose);
    missionFact('translate', 'خدمت زبانی', language);
    missionFact(m.car ? 'directions_car' : 'directions_walk', 'نوع همراهی', m.car ? 'با خودرو' : 'پیاده');
    missionFact('pin_drop', 'محل قرار ملاقات', m.place || 'نشانی ثبت نشده');
    missionFact('groups', 'تعداد مسافران', HZ.toFa(m.party) + ' نفر');
    card.appendChild(facts);

    var note = el('div', 'translator-offer-notes');
    note.appendChild(el('span', 'material-symbols-outlined translator-offer-note-icon', 'format_quote'));
    var noteCopy = el('div', 'translator-offer-note-copy');
    noteCopy.appendChild(el('small', '', 'یادداشت مسافر'));
    noteCopy.appendChild(el('strong', '', m.notes ? '«' + m.notes + '»' : 'یادداشتی ثبت نشده است'));
    note.appendChild(noteCopy); card.appendChild(note);

    // A meeting pin is shown only after acceptance and only from the server's validated coordinates.
    if (hasMissionCoordinates(m)) {
      var mapButton = el('button', 'translator-map-focus', 'نمایش محل ملاقات روی نقشه');
      mapButton.type = 'button';
      mapButton.addEventListener('click', function () { focusMissionOnMap(m); });
      card.appendChild(mapButton);
    }

    if (!m.started && !m.arrived_at) {
      var arrivalCard = el('div', 'translator-mission-state-card');
      if (futureAppointment) {
        var appointment = new Date(m.scheduled_at);
        arrivalCard.appendChild(el('div', 'translator-mission-state-copy', 'زمان قرار ' + HZ.jDate(appointment) + '، ساعت ' + HZ.clock(appointment) + ' است؛ ثبت حضور در موعد فعال می‌شود.'));
      } else {
        arrivalCard.appendChild(el('div', 'translator-mission-state-copy', 'پس از رسیدن، حضور را ثبت کنید. ثبت حضور دستی است و موقعیت دستگاه خوانده نمی‌شود.'));
        var arrivalButton = el('button', 'translator-offer-accept translator-mission-primary-action');
        arrivalButton.type = 'button';
        var arrivalIcon = el('span', 'material-symbols-outlined', 'where_to_vote');
        arrivalIcon.setAttribute('aria-hidden', 'true');
        arrivalButton.appendChild(arrivalIcon);
        arrivalButton.appendChild(el('span', '', 'رسیدم به محل ملاقات'));
        HZ_MISSION_ACTION.bind(arrivalButton, m.reservation_id);
        arrivalButton.onclick = function () { serviceAction('arrive', m, undefined, actor); };
        arrivalCard.appendChild(arrivalButton);
      }
      card.appendChild(arrivalCard);
    }

    if (!m.started && m.arrived_at && futureAppointment) {
      var waitingCard = el('div', 'translator-mission-state-card');
      var waitingAt = new Date(m.scheduled_at);
      waitingCard.appendChild(el('div', 'translator-mission-state-copy', 'حضور قبلی ثبت شده است؛ به‌دلیل زمان قرار جدید، شروع خدمت پس از ' + HZ.jDate(waitingAt) + '، ساعت ' + HZ.clock(waitingAt) + ' در دسترس می‌شود.'));
      card.appendChild(waitingCard);
    }

    if (!m.started && m.arrived_at && !futureAppointment) {
      var otpCard = el('div', 'translator-otp-card');
      var otpHeading = el('div', 'translator-otp-heading');
      otpHeading.appendChild(el('strong', '', 'کد تأیید ۵ رقمی شروع خدمت'));
      otpHeading.appendChild(el('small', '', 'کد را از مسافر بپرسید'));
      otpCard.appendChild(otpHeading);
      otpCard.appendChild(el('p', 'translator-otp-note', 'برای شروع، فقط کدی را وارد کنید که مسافر به شما می‌گوید. کد محرمانه در این صفحه نمایش داده نمی‌شود.'));
      var codeInputs = el('div', 'translator-otp-inputs');
      codeInputs.dir = 'ltr';
      var inputs = [];
      for (var ci = 0; ci < 5; ci++) {
        (function (idx) {
          var input = document.createElement('input');
          input.type = 'text'; input.inputMode = 'numeric'; input.maxLength = 1; input.autocomplete = 'off';
          input.className = 'translator-otp-digit';
          input.setAttribute('aria-label', 'رقم ' + HZ.toFa(idx + 1) + ' از کد پنج‌رقمی که مسافر اعلام می‌کند');
          input.setAttribute('pattern', '[0-9۰-۹٠-٩]');
          input.addEventListener('input', function () {
            var digits = HZ.toEn(input.value).replace(/\D/g, '');
            input.value = digits.slice(-1);
            if (input.value && idx < inputs.length - 1) inputs[idx + 1].focus();
          });
          input.addEventListener('keydown', function (event) {
            if (event.key === 'Backspace' && !input.value && idx > 0) inputs[idx - 1].focus();
            if (event.key === 'ArrowLeft' && idx < inputs.length - 1) inputs[idx + 1].focus();
            if (event.key === 'ArrowRight' && idx > 0) inputs[idx - 1].focus();
          });
          input.addEventListener('paste', function (event) {
            event.preventDefault();
            var text = event.clipboardData && event.clipboardData.getData('text') || '';
            var digits = HZ.toEn(text).replace(/\D/g, '');
            for (var pi = 0; pi < digits.length && idx + pi < inputs.length; pi++) inputs[idx + pi].value = digits[pi];
            var next = Math.min(idx + digits.length, inputs.length - 1);
            inputs[next].focus();
          });
          inputs.push(input); codeInputs.appendChild(input);
        })(ci);
      }
      otpCard.appendChild(codeInputs);
      var verify = el('button', 'translator-offer-accept translator-mission-primary-action');
      verify.type = 'button';
      var verifyIcon = el('span', 'material-symbols-outlined', 'lock_open');
      verifyIcon.setAttribute('aria-hidden', 'true');
      verify.appendChild(verifyIcon);
      verify.appendChild(el('span', '', 'تأیید کد و آغاز همراهی'));
      HZ_MISSION_ACTION.bind(verify, m.reservation_id);
      verify.onclick = function () { serviceAction('start', m, inputs.map(function (input) { return input.value; }).join(''), actor); };
      otpCard.appendChild(verify); card.appendChild(otpCard);
    }

    if (m.started) {
      var activeCard = el('div', 'translator-active-service-card');
      var activeHead = el('div', 'translator-active-service-heading');
      activeHead.appendChild(el('span', 'material-symbols-outlined', 'schedule'));
      var activeCopy = el('div', 'translator-active-service-copy');
      activeCopy.appendChild(el('strong', '', 'همراهی و ترجمه همزمان در حال اجرا'));
      activeCopy.appendChild(el('small', '', 'زمان سپری‌شده از شروع ثبت‌شده در سرور'));
      activeHead.appendChild(activeCopy);
      activeCard.appendChild(activeHead);
      var serviceTimer = el('div', 'translator-service-timer');
      serviceTimer.appendChild(el('span', 'material-symbols-outlined translator-service-timer-icon', 'schedule'));
      var timerValue = el('span', 'translator-service-timer-value', 'در حال محاسبه از زمان سرور…');
      timerValue.setAttribute('data-service-clock', '1');
      timerValue.setAttribute('data-service-started-at', String(Date.parse(m.service_started_at)));
      timerValue.setAttribute('data-service-hours', String(m.hours));
      serviceTimer.appendChild(timerValue);
      serviceTimer.setAttribute('role', 'timer');
      serviceTimer.setAttribute('aria-live', 'off');
      activeCard.appendChild(serviceTimer);
      activeCard.appendChild(renderExtension(m));
      activeCard.appendChild(el('p', 'translator-service-terms', 'پایان خدمت را مسافر ثبت می‌کند؛ اگر زودتر تمام کند، مبلغ کامل توافق‌شده محفوظ است.'));
      if (m.finish_requested) {
        activeCard.appendChild(el('div', 'translator-finish-pending', 'درخواست پایان ارسال شده؛ خدمت با مبلغ کامل تا تصمیم مسافر برقرار می‌ماند.'));
      } else {
        var finishButton = el('button', 'translator-offer-reject translator-mission-danger-action');
        finishButton.type = 'button';
        var finishIcon = el('span', 'material-symbols-outlined', 'flag');
        finishIcon.setAttribute('aria-hidden', 'true');
        finishButton.appendChild(finishIcon);
        finishButton.appendChild(el('span', '', 'درخواست پایان مأموریت'));
        HZ_MISSION_ACTION.bind(finishButton, m.reservation_id);
        finishButton.onclick = function () { openFinishModal(m, finishButton); };
        activeCard.appendChild(finishButton);
      }
      card.appendChild(activeCard);
    }

    if (!m.started) {
      var cancelButton = el('button', 'translator-mission-cancel neu-flat-sm');
      cancelButton.type = 'button';
      var cancelIcon = el('span', 'material-symbols-outlined', 'close');
      cancelIcon.setAttribute('aria-hidden', 'true');
      cancelButton.appendChild(cancelIcon);
      cancelButton.appendChild(el('span', '', 'لغو مأموریت'));
      HZ_MISSION_ACTION.bind(cancelButton, m.reservation_id);
      cancelButton.onclick = function () { serviceAction('cancel', m, undefined, actor); };
      card.appendChild(cancelButton);
      card.appendChild(el('small', 'translator-mission-cancel-note', 'لغو پیش از شروع امتیاز را کاهش می‌دهد؛ پیدا شدن مترجم جایگزین قطعی نیست.'));
    }
    return card;
  }

  // ---------- پرداخت‌های منتظر تأیید (سند ۷.۳) ----------
  var PAYMENTS_LIST = [], SETTLEMENTS_LIST = [], paymentsState = 'loading', paymentOwnerToken = null;
  var paymentRead = 0, paymentApplied = 0, paymentRevision = 0;
  function loadPayments(invalidate) {
    var token = tok(), read = ++paymentRead, revision = invalidate ? ++paymentRevision : paymentRevision;
    if (!token) { paymentOwnerToken = null; PAYMENTS_LIST = []; SETTLEMENTS_LIST = []; paymentsState = 'error'; renderPayments(); return; }
    fetch('/api/translator/payments', { headers: H.authHeaders(token), cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('payments'); return r.json(); })
      .then(function (d) {
        if (tok() !== token || revision !== paymentRevision || read < paymentApplied) return;
        if (!d || !Array.isArray(d.payments) || !Array.isArray(d.settlements) || !d.payments.every(function (p) {
          return p && Number.isSafeInteger(p.reservation_id) && p.reservation_id > 0 &&
            typeof p.total === 'number' && Number.isFinite(p.total) && p.total >= 0 &&
            typeof p.net === 'number' && Number.isFinite(p.net) && p.net >= 0 && typeof p.confirmed === 'boolean' &&
            [null, 'cash', 'online'].includes(p.pay_method) && [null, 'awaiting_cash', 'disputed'].includes(p.pay_state) &&
            (p.pay_state === null || p.pay_method === 'cash');
        }) || !d.settlements.every(function (s) {
          return s && Number.isSafeInteger(s.reservation_id) && s.reservation_id > 0 &&
            typeof s.total === 'number' && Number.isFinite(s.total) && s.total >= 0 &&
            typeof s.net === 'number' && Number.isFinite(s.net) && s.net >= 0 && Number.isInteger(s.hours) && s.hours >= 1 && s.hours <= 24 &&
            ['cash', 'online'].includes(s.pay_method) && s.pay_state === 'settled' && s.confirmed === true && s.traveler_paid === true &&
            typeof s.finished_at === 'string' && Number.isFinite(Date.parse(s.finished_at)) &&
            (s.place == null || typeof s.place === 'string') && (s.travelerName == null || typeof s.travelerName === 'string');
        }) || new Set(d.payments.map(function (p) { return p.reservation_id; })).size !== d.payments.length ||
          new Set(d.settlements.map(function (s) { return s.reservation_id; })).size !== d.settlements.length) throw new Error('payments');
        paymentOwnerToken = token; paymentApplied = read; PAYMENTS_LIST = d.payments; SETTLEMENTS_LIST = d.settlements; paymentsState = 'ok'; renderPayments();
      })
      .catch(function () {
        if (tok() !== token || revision !== paymentRevision || read < paymentApplied) return;
        paymentOwnerToken = token; paymentApplied = read; PAYMENTS_LIST = []; SETTLEMENTS_LIST = []; paymentsState = 'error'; renderPayments();
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
    if (paymentsState === 'loading') {
      box.appendChild(el('span', 'translator-empty-offers', 'در حال دریافت وضعیت پرداخت‌ها از سرور…'));
      return;
    }
    if (paymentsState === 'error') {
      box.appendChild(el('span', 'text-[12px] text-error', 'وضعیت پرداخت‌ها دریافت نشد؛ اتصال را بررسی کنید و دوباره تلاش کنید.'));
      var retry = el('button', 'text-[12px] font-bold text-primary', 'دریافت دوبارهٔ پرداخت‌ها');
      retry.type = 'button'; retry.onclick = function () { loadPayments(true); }; box.appendChild(retry);
      return;
    }
    if (!PAYMENTS_LIST.length && !SETTLEMENTS_LIST.length) {
      box.appendChild(el('span', 'translator-empty-offers', 'پرداخت نیازمند پیگیری از سرور دریافت نشد.'));
      return;
    }
    if (PAYMENTS_LIST.length) {
      box.appendChild(el('span', 'text-[11px] font-bold text-on-surface', 'پرداخت‌های منتظر تأیید'));
      PAYMENTS_LIST.forEach(function (p) { box.appendChild(paymentCard(p)); });
    }
    if (SETTLEMENTS_LIST.length) {
      box.appendChild(el('span', 'text-[11px] font-bold text-on-surface', 'خلاصهٔ تسویه‌های نهایی'));
      SETTLEMENTS_LIST.forEach(function (s) { box.appendChild(settlementCard(s)); });
    }
  }
  function settlementCard(s) {
    var card = el('article', 'translator-payment-card translator-settlement-card');
    card.setAttribute('data-settlement-reservation', s.reservation_id);
    var heading = el('div', 'translator-payment-heading');
    heading.appendChild(el('span', 'material-symbols-outlined', 'verified'));
    var title = el('div', 'translator-payment-title');
    title.appendChild(el('strong', '', s.place || 'صورت‌حساب نهایی مأموریت'));
    title.appendChild(el('small', '', 'مسافر: ' + (s.travelerName || 'نام اعلام نشده')));
    heading.appendChild(title); card.appendChild(heading);
    var summary = el('div', 'translator-payment-summary');
    [['مدت نهایی قرارداد', HZ.toFa(s.hours) + ' ساعت'],
      ['مبلغ کل توافق‌شده', HZ.money(s.total) + ' تومان'],
      ['سهم خالص مترجم', HZ.money(s.net) + ' تومان'],
      ['روش پرداخت', s.pay_method === 'cash' ? 'نقدی' : 'آنلاین']].forEach(function (row, index) {
        var line = el('div', 'translator-payment-row' + (index === 2 ? ' translator-payment-net' : ''));
        line.appendChild(el('span', '', row[0])); line.appendChild(el('strong', '', row[1])); summary.appendChild(line);
      });
    card.appendChild(summary);
    var date = new Date(s.finished_at);
    card.appendChild(el('p', 'translator-payment-state', 'وضعیت تسویه: نهایی و تأییدشده در سرور • ' + HZ.jDate(date) + '، ' + HZ.clock(date)));
    return card;
  }
  function paymentCard(p) {
    var card = el('article', 'translator-payment-card');
    card.setAttribute('data-payment-reservation', p.reservation_id);
    var heading = el('div', 'translator-payment-heading');
    heading.appendChild(el('span', 'material-symbols-outlined', 'receipt_long'));
    var title = el('div', 'translator-payment-title');
    title.appendChild(el('strong', '', p.place || 'خلاصهٔ تسویهٔ مأموریت'));
    title.appendChild(el('small', '', 'مسافر: ' + (p.travelerName || 'نام اعلام نشده')));
    heading.appendChild(title); card.appendChild(heading);
    var summary = el('div', 'translator-payment-summary');
    var total = el('div', 'translator-payment-row');
    total.appendChild(el('span', '', 'مبلغ کل توافق‌شده'));
    total.appendChild(el('strong', '', HZ.money(p.total) + ' تومان'));
    summary.appendChild(total);
    var net = el('div', 'translator-payment-row translator-payment-net');
    net.appendChild(el('span', '', 'سهم خالص مترجم'));
    net.appendChild(el('strong', '', HZ.money(p.net) + ' تومان'));
    summary.appendChild(net); card.appendChild(summary);
    var state;
    if (p.pay_state === 'disputed') state = 'اختلاف پرداخت ثبت شده است؛ هنوز تسویه نشده.';
    else if (!p.pay_state) state = 'منتظر انتخاب روش پرداخت توسط مسافر.';
    else if (p.confirmed) state = 'دریافت شما ثبت شد؛ منتظر تأیید مسافر.';
    else state = 'مسافر پرداخت نقدی را ثبت کرده است؛ دریافت واقعی وجه را بررسی کنید.';
    card.appendChild(el('p', 'translator-payment-state', state));
    if (p.pay_method === 'cash' && p.pay_state === 'awaiting_cash' && !p.confirmed) {
      var row = el('div', 'translator-offer-actions translator-payment-actions');
      var ok = el('button', 'translator-offer-accept');
      ok.type = 'button';
      var paymentIcon = el('span', 'material-symbols-outlined', 'payments');
      paymentIcon.setAttribute('aria-hidden', 'true');
      ok.appendChild(paymentIcon);
      ok.appendChild(el('span', '', 'دریافت وجه را تأیید می‌کنم'));
      HZ_MISSION_ACTION.bind(ok, p.reservation_id);
      ok.onclick = function () { openCashModal(p, ok); };
      var no = el('button', 'translator-offer-reject');
      no.type = 'button';
      var disputeIcon = el('span', 'material-symbols-outlined', 'report_problem');
      disputeIcon.setAttribute('aria-hidden', 'true');
      no.appendChild(disputeIcon);
      no.appendChild(el('span', '', 'اختلاف دارم'));
      HZ_MISSION_ACTION.bind(no, p.reservation_id);
      no.onclick = function () { openCashModal(p, no); };
      row.appendChild(no); row.appendChild(ok); card.appendChild(row);
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
      metaText = 'فرصت پاسخ: ' + HZ.toFa(Math.max(0, Math.ceil((Date.parse(pendingResponse.expires_at) - (Date.now() + offerServerClockOffset)) / 1000))) + ' ثانیه';
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
    var tm = el('span', 'font-bold text-secondary', HZ.toFa(Math.max(0, Math.ceil((Date.parse(c.expires_at) - (Date.now() + offerServerClockOffset)) / 1000))) + ' ثانیه');
    tm.setAttribute('data-exp', c.expires_at); tm.setAttribute('data-pure', '1');
    row.appendChild(tm);
    var btns = el('div', 'flex gap-2');
    var no = el('button', 'px-4 py-2 rounded-xl neu-raised text-[12px] font-bold text-on-surface cursor-pointer', 'رد');
    no.type = 'button';
    HZ_MISSION_ACTION.bind(no, c.reservation_id);
    function decideChange(action) {
      return HZ_MISSION_ACTION.run({ action: action, id: c.id, reservation_id: c.reservation_id, changes: c.changes, token: actor,
        serverTimeOffset: offerServerClockOffset, refresh: function () { loadMissions(); refreshOffers(true); } });
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
  function renderExtension(m) {
    var request = lastExtensions.find(function (e) { return e.reservation_id === m.reservation_id; }) || null;
    var card = el('section', 'translator-extension-card');
    card.setAttribute('aria-label', 'وضعیت درخواست تمدید خدمت');
    var heading = el('div', 'translator-extension-heading');
    heading.appendChild(el('span', 'material-symbols-outlined', 'more_time'));
    var title = el('div', 'translator-extension-copy');
    title.appendChild(el('strong', '', 'درخواست تمدید خدمت'));
    title.appendChild(el('small', '', request ? 'درخواست تازهٔ مسافر؛ نیازمند تصمیم مترجم' : 'درخواست تمدید فقط از سوی مسافر در سرور ثبت می‌شود'));
    heading.appendChild(title); card.appendChild(heading);
    if (request) {
      var details = el('div', 'translator-extension-details');
      details.appendChild(el('span', '', 'تمدید درخواستی: ' + HZ.toFa(request.extra_hours) + ' ساعت'));
      details.appendChild(el('span', '', 'مبلغ اضافه: ' + HZ.money(request.extra_total) + ' تومان'));
      details.appendChild(el('strong', '', 'سهم پس از پذیرش: ' + HZ.money(request.new_net) + ' تومان'));
      card.appendChild(details);
      var open = el('button', 'translator-extension-review');
      open.type = 'button';
      var reviewIcon = el('span', 'material-symbols-outlined', 'fact_check');
      reviewIcon.setAttribute('aria-hidden', 'true');
      open.appendChild(reviewIcon);
      open.appendChild(el('span', '', 'بررسی درخواست تمدید'));
      HZ_MISSION_ACTION.bind(open, m.reservation_id);
      open.onclick = function () { openExtensionModal(request, open); };
      card.appendChild(open);
    } else {
      card.appendChild(el('p', 'translator-extension-unavailable-note', 'فعلاً درخواست تمدیدی برای تأیید ندارید؛ مبلغ و زمان قرارداد فعلی بدون تغییر است.'));
      var unavailable = el('button', 'translator-extension-review');
      unavailable.type = 'button'; unavailable.disabled = true;
      unavailable.appendChild(el('span', 'material-symbols-outlined', 'hourglass_empty'));
      unavailable.appendChild(el('span', '', 'درخواستی برای بررسی نیست'));
      card.appendChild(unavailable);
    }
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
      if (missionsState === 'ok') renderMissions();
      updateTranslatorMap();
      updateWorkspaceSheetSummary();
      syncWorkspaceEmptyMissions();
      return;
    }
    lastChanges.forEach(function (c) { offersBox.appendChild(renderChange(c)); });
    if (offersState === 'ok' && !lastExtensions.length && !lastChanges.length && !lastOffers.length) {
      offersBox.appendChild(el('div', 'translator-empty-offers', 'در حال حاضر پیشنهاد یا درخواست تغییری برای پاسخ ثبت نشده است.'));
    }
    lastOffers.forEach(function (o) {
      var card = el('article', 'translator-offer-card');
      var actor = tok();
      card.setAttribute('data-offer-id', o.id);

      var primary = el('div', 'translator-offer-primary');
      var summary = el('div', 'translator-offer-summary');
      summary.appendChild(el('strong', 'translator-offer-traveler', o.traveler_name || 'نام مسافر اعلام نشده'));
      var stateLine = el('div', 'translator-offer-state-line');
      stateLine.appendChild(el('span', 'translator-offer-state-title', 'پیشنهاد جدید منتظر بررسی'));
      stateLine.appendChild(el('span', 'translator-offer-state-dot', ''));
      stateLine.appendChild(el('span', 'translator-offer-kind', o.kind === 'scheduled' ? 'درخواست زمان‌دار' : 'درخواست فوری'));
      summary.appendChild(stateLine);
      if (o.kind === 'scheduled' && o.scheduled_at) {
        var scheduled = new Date(o.scheduled_at);
        summary.appendChild(el('small', 'translator-offer-kind-detail', HZ.jDate(scheduled) + ' • ' + HZ.clock(scheduled)));
      }
      var remaining = Math.max(0, Math.ceil((Date.parse(o.expires_at) - (Date.now() + offerServerClockOffset)) / 1000));
      var expiryLine = el('small', 'translator-offer-expiry', 'انقضا در ' + HZ.toFa(remaining) + ' ثانیه');
      expiryLine.setAttribute('data-exp', o.expires_at);
      expiryLine.setAttribute('data-offer-expiry', '1');
      summary.appendChild(expiryLine);
      primary.appendChild(summary);

      var timer = el('div', 'translator-offer-countdown');
      timer.setAttribute('role', 'timer');
      timer.setAttribute('aria-label', 'فرصت پاسخ به پیشنهاد');
      var ring = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      ring.setAttribute('viewBox', '0 0 44 44');
      ring.setAttribute('class', 'translator-offer-countdown-svg');
      var track = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      track.setAttribute('cx', '22'); track.setAttribute('cy', '22'); track.setAttribute('r', '17');
      track.setAttribute('class', 'translator-offer-countdown-track');
      var progress = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      progress.setAttribute('cx', '22'); progress.setAttribute('cy', '22'); progress.setAttribute('r', '17');
      progress.setAttribute('class', 'translator-offer-countdown-progress');
      progress.setAttribute('stroke-dasharray', '106.8');
      var offerDurationMs = Math.max(1, Date.parse(o.expires_at) - Date.parse(o.created_at));
      var offerElapsed = Math.min(1, Math.max(0, 1 - (Date.parse(o.expires_at) - (Date.now() + offerServerClockOffset)) / offerDurationMs));
      progress.setAttribute('stroke-dashoffset', String(106.8 * offerElapsed));
      progress.setAttribute('data-exp', o.expires_at);
      progress.setAttribute('data-countdown-progress', '1');
      progress.setAttribute('data-countdown-total-ms', String(offerDurationMs));
      ring.appendChild(track); ring.appendChild(progress);
      var count = el('span', 'translator-offer-countdown-value', HZ.toFa(remaining));
      count.setAttribute('data-exp', o.expires_at);
      count.setAttribute('data-countdown-ring', '1');
      timer.appendChild(ring); timer.appendChild(count);
      primary.appendChild(timer);

      var compensation = el('div', 'translator-offer-compensation');
      compensation.appendChild(el('small', '', 'حق‌الزحمه تعهد (' + HZ.toFa(o.hours) + ' ساعت)'));
      compensation.appendChild(el('strong', '', HZ.money(o.net)));
      compensation.appendChild(el('small', 'translator-offer-currency', 'سهم خالص مترجم'));
      primary.appendChild(compensation);
      card.appendChild(primary);

      var facts = el('div', 'translator-offer-facts');
      function offerFact(icon, label, value) {
        var fact = el('div', 'translator-offer-fact');
        fact.appendChild(el('span', 'material-symbols-outlined translator-offer-fact-icon', icon));
        var copy = el('div', 'translator-offer-fact-copy');
        copy.appendChild(el('small', '', label));
        copy.appendChild(el('strong', '', value));
        fact.appendChild(copy);
        facts.appendChild(fact);
      }
      var language = (LANGUAGE_LABEL_FA[o.origin_lang] || o.origin_lang) + ' ⟷ ' + (LANGUAGE_LABEL_FA[o.dest_lang] || o.dest_lang);
      if (o.field && o.field !== 'general') language += ' • ' + (FIELD_LABEL_FA[o.field] || o.field);
      offerFact('translate', 'خدمت زبانی', language);
      offerFact(o.car ? 'directions_car' : 'directions_walk', 'نوع همراهی', o.car ? 'با خودرو' : 'پیاده');
      offerFact('pin_drop', 'محل قرار ملاقات', o.place || 'نشانی در درخواست ثبت نشده');
      offerFact('groups', 'تعداد مسافران', HZ.toFa(o.party) + ' نفر');
      card.appendChild(facts);

      var note = el('div', 'translator-offer-notes');
      note.appendChild(el('span', 'material-symbols-outlined translator-offer-note-icon', 'format_quote'));
      var noteCopy = el('div', 'translator-offer-note-copy');
      noteCopy.appendChild(el('small', '', 'یادداشت مسافر'));
      noteCopy.appendChild(el('strong', '', o.notes ? '«' + o.notes + '»' : 'یادداشتی ثبت نشده است'));
      note.appendChild(noteCopy);
      card.appendChild(note);

      var btns = el('div', 'translator-offer-actions');
      var no = el('button', 'translator-offer-reject');
      no.type = 'button'; no.setAttribute('aria-label', 'رد درخواست');
      no.appendChild(el('span', 'material-symbols-outlined', 'close'));
      no.appendChild(el('span', '', 'رد درخواست'));
      HZ_MISSION_ACTION.bind(no, o.reservation_id);
      function decideOffer(action) {
        return HZ_MISSION_ACTION.run({ action: action, id: o.id, reservation_id: o.reservation_id, net: o.net, token: actor,
          serverTimeOffset: offerServerClockOffset, refresh: function () { loadMissions(); refreshOffers(true); } });
      }
      no.onclick = function () { decideOffer('offer-decline'); };
      var yes = el('button', 'translator-offer-accept');
      yes.type = 'button'; yes.setAttribute('aria-label', 'پذیرش مأموریت و اعزام');
      yes.appendChild(el('span', 'material-symbols-outlined', 'check_circle'));
      yes.appendChild(el('span', '', 'قبول مأموریت و اعزام'));
      HZ_MISSION_ACTION.bind(yes, o.reservation_id);
      yes.onclick = function () { decideOffer('offer-accept'); };
      btns.appendChild(no); btns.appendChild(yes);
      card.appendChild(btns);
      offersBox.appendChild(card);
    });
    updateTranslatorMap();
    updateWorkspaceSheetSummary();
    syncWorkspaceEmptyMissions();
  }
  var offersSig = '', offersState = 'loading';
  var offerRead = 0, offerApplied = 0, offerRevision = 0, offerServerClockOffset = 0;
  function refreshOffers(invalidate) {
    var token = tok(), read = ++offerRead, revision = invalidate ? ++offerRevision : offerRevision;
    if (!token) return;
    srv('GET', '/translator/offers').then(function (res) {
      if (tok() !== token || revision !== offerRevision || read < offerApplied) return;
      if (res.status !== 200 || !res.data || !Number.isFinite(Date.parse(res.data.server_time)) || !Array.isArray(res.data.offers) || !Array.isArray(res.data.changes) || !Array.isArray(res.data.extensions) ||
          !res.data.changes.every(function (c) { return c && Number.isSafeInteger(c.id) && c.id > 0 && Number.isSafeInteger(c.reservation_id) && c.reservation_id > 0 &&
            typeof c.expires_at === 'string' && Number.isFinite(Date.parse(c.expires_at)) && HZ_MISSION_ACTION.validChanges(c.changes); }) ||
          !res.data.extensions.every(function (e) { return e && Number.isSafeInteger(e.id) && e.id > 0 && Number.isSafeInteger(e.reservation_id) && e.reservation_id > 0 &&
            Number.isInteger(e.extra_hours) && e.extra_hours >= 1 && e.extra_hours <= 4 && typeof e.extra_total === 'number' && Number.isFinite(e.extra_total) && e.extra_total >= 0 &&
            typeof e.extra_net === 'number' && Number.isFinite(e.extra_net) && e.extra_net >= 0 && typeof e.new_net === 'number' && Number.isFinite(e.new_net) && e.new_net >= 0 &&
            typeof e.expires_at === 'string' && Number.isFinite(Date.parse(e.expires_at)) &&
            (e.traveler_name == null || typeof e.traveler_name === 'string') && (e.place == null || typeof e.place === 'string'); }) ||
          !res.data.offers.every(function (o) { return o && Number.isSafeInteger(o.id) && o.id > 0 && Number.isSafeInteger(o.reservation_id) && o.reservation_id > 0 &&
            ['instant', 'scheduled'].includes(o.kind) && typeof o.created_at === 'string' && Number.isFinite(Date.parse(o.created_at)) &&
            typeof o.expires_at === 'string' && Number.isFinite(Date.parse(o.expires_at)) && typeof o.net === 'number' && Number.isFinite(o.net) && o.net >= 0 &&
            Number.isInteger(o.hours) && o.hours >= 1 && o.hours <= 24 && (o.car === 0 || o.car === 1) && Number.isInteger(o.party) && o.party >= 1 && o.party <= 20 &&
            (o.kind !== 'scheduled' || (typeof o.scheduled_at === 'string' && Number.isFinite(Date.parse(o.scheduled_at)))) &&
            (o.traveler_name == null || typeof o.traveler_name === 'string') && (o.place == null || typeof o.place === 'string') &&
            (o.notes == null || typeof o.notes === 'string'); }) ||
          new Set(res.data.offers.map(function (o) { return o.id; })).size !== res.data.offers.length) {
        offerApplied = read; offersState = 'error'; offersSig = ''; lastOffers = []; lastChanges = []; lastExtensions = []; renderOffers(); return;
      }
      offersState = 'ok';
      offerServerClockOffset = Date.parse(res.data.server_time) - Date.now();
      offerApplied = read;
      lastOffers = res.data.offers;
      lastChanges = res.data.changes;
      lastExtensions = res.data.extensions;
      // Quote changes as well as IDs invalidate cards. Re-rendered controls
      // inherit the reservation lock, never silently unlocking an action.
      var sig = JSON.stringify([lastOffers, lastChanges, lastExtensions]);
      if (sig !== offersSig) {
        offersSig = sig; renderOffers();
        if (missionsState === 'ok') renderMissions();
      }
      HZ_MISSION_ACTION.update();
    });
  }
  setInterval(refreshOffers, 3000);
  loadPayments(); setInterval(loadPayments, 5000);
  // شمارش معکوس هر ثانیه، بدون بازسازی کارت‌ها
  setInterval(function () {
    var serverNow = Date.now() + offerServerClockOffset;
    document.querySelectorAll('[data-exp]').forEach(function (t) {
      var expiresAt = Date.parse(t.getAttribute('data-exp'));
      if (!Number.isFinite(expiresAt)) return;
      var left = Math.max(0, Math.ceil((expiresAt - serverNow) / 1000));
      if (t.getAttribute('data-countdown-progress')) {
        var total = Number(t.getAttribute('data-countdown-total-ms'));
        var elapsed = Number.isFinite(total) && total > 0 ? Math.min(1, Math.max(0, 1 - (expiresAt - serverNow) / total)) : 1;
        t.setAttribute('stroke-dashoffset', String(106.8 * elapsed));
      } else if (t.getAttribute('data-countdown-ring')) t.textContent = HZ.toFa(left);
      else if (t.getAttribute('data-pure')) t.textContent = HZ.toFa(left) + ' ثانیه';
      else if (t.getAttribute('data-offer-expiry')) t.textContent = 'انقضا در ' + HZ.toFa(left) + ' ثانیه';
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
