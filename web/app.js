/* 화면 렌더링. 판단 문구는 쓰지 않고 수신 상태와 수치만 보여준다. */
(function () {
  'use strict';

  var L = window.NPP;
  // 측정 데이터는 사이트(Pages)가 아니라 저장소의 data 브랜치에서 읽는다.
  // Pages 는 같은 커밋으로 반복 배포하면 "성공"으로 끝나고도 사이트에 반영하지 않는 일이 있었다(2026-11-05, 11-10).
  // raw.githubusercontent.com 은 다른 출처에서도 읽을 수 있고(CORS 허용) CDN 이 최대 5분 캐시한다.
  // window.NPP_DATA_BASE 는 시험용 재정의(서비스 워커에도 같은 값을 넘긴다).
  var DATA_BASE = window.NPP_DATA_BASE || 'https://raw.githubusercontent.com/ZDragon0527/NPP_Discharge_Temp/data/';
  var DATA_URL = DATA_BASE + 'latest.json';
  var HISTORY_URL = DATA_BASE + 'history.json';
  var REFETCH_MS = 5 * 60 * 1000;    // 현재 값 다시 받기
  var HISTORY_REFETCH_MS = 15 * 60 * 1000;   // 이력(수백 KB)은 덜 자주 받는다
  var RERENDER_MS = 60 * 1000;       // 경과 시간 표시 갱신
  var DEFAULT_CODE = 'WS';           // 기본 본부: 월성
  var CODES = L.PLANTS.map(function (p) { return p.code; });

  var STATUS = {
    ok:      { label: '수신 중',     icon: '•', cls: 'ok' },
    partial: { label: '일부 수신 지연', icon: '▲', cls: 'warn' },
    stale:   { label: '수신 중단',   icon: '■', cls: 'bad' },
    error:   { label: '조회 오류',   icon: '▲', cls: 'warn' },
    nodata:  { label: '데이터 없음', icon: '■', cls: 'bad' }
  };

  var PLANT_REGIONS = {
    WS: '경상북도 경주시 양남면 일원',
    KR: '부산광역시 기장군 장안읍 일원',
    YK: '전라남도 영광군 홍농읍 일원',
    UJ: '경상북도 울진군 북면 일원'
  };

  var state = { latest: null, loadError: null, lastFetchMs: 0, history: null, historyError: false, historyFetchedMs: 0, fromCache: false };
  var wide = window.matchMedia('(min-width: 900px)');

  function $(id) { return document.getElementById(id); }

  function h(tag, props) {
    var el = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      var v = props[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.indexOf('on') === 0) el[k] = v;
      else el.setAttribute(k, v);
    });
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(el, c); }); return; }
    el.appendChild(child.nodeType ? child : document.createTextNode(String(child)));
  }

  function kstString(ms) {
    return new Date(ms + 9 * 3600 * 1000).toISOString().slice(0, 16).replace('T', ' ');
  }

  function currentCode() {
    var code = (location.hash || '').replace('#', '').toUpperCase();
    if (code === 'ALL' || CODES.indexOf(code) >= 0) return code;
    return DEFAULT_CODE;
  }

  function views(now) {
    var limit = (state.latest && state.latest.stale_after_minutes) || L.DEFAULT_STALE_MINUTES;
    var plants = (state.latest && state.latest.plants) || {};
    return L.PLANTS.map(function (p) { return L.buildPlantView(p.code, plants[p.code], now, limit); });
  }

  function badge(status) {
    var s = STATUS[status];
    return h('span', { class: 'badge ' + s.cls }, h('span', { 'aria-hidden': 'true', text: s.icon }), s.label);
  }

  /* ---- 상단 히어로 배너 및 헤더 상태 배지 ---- */
  function renderHero(vs, targetCode, now) {
    var heroEl = $('hero');
    if (!heroEl) return;

    var code = targetCode && targetCode !== 'ALL' ? targetCode : DEFAULT_CODE;
    var v = vs.filter(function (it) { return it.code === code; })[0] || vs[0];
    if (!v) return;

    var st = STATUS[v.status] || STATUS.nodata;

    // 상단 헤더 라이브 상태 배지 동기화
    var headerBadge = $('header-status-badge');
    var headerText = $('header-status-text');
    if (headerBadge && headerText) {
      var okCount = vs.filter(function (it) { return it.status === 'ok'; }).length;
      headerBadge.className = 'status-pill ' + (okCount === vs.length ? 'ok' : (okCount > 0 ? 'warn' : 'bad'));
      headerText.textContent = vs.length + '개 본부 중 ' + okCount + '개소 수신 중';
    }

    // 히어로 배너 상태 필
    var heroBadgeWrap = $('hero-badge-wrap');
    var heroStatusText = $('hero-status-text');
    if (heroBadgeWrap && heroStatusText) {
      heroBadgeWrap.className = 'hero-status-pill ' + st.cls;
      heroStatusText.textContent = v.name + ' 본부 · ' + st.label;
    }

    var titleEl = $('hero-plant-title');
    if (titleEl) titleEl.textContent = v.name + ' 원자력발전소 온배수 현황';

    var regionEl = $('hero-plant-region');
    if (regionEl) regionEl.textContent = PLANT_REGIONS[v.code] || '원자력발전소 주변 해역';

    var inTempItem = v.items.inTemp;
    var outTempItem = v.items.outTemp;
    var inSalItem = v.items.inSal;
    var outSalItem = v.items.outSal;

    var inTempOk = inTempItem && !inTempItem.stale && inTempItem.num !== null;
    var outTempOk = outTempItem && !outTempItem.stale && outTempItem.num !== null;
    var inSalOk = inSalItem && !inSalItem.stale && inSalItem.num !== null;
    var outSalOk = outSalItem && !outSalItem.stale && outSalItem.num !== null;

    var heroInTemp = $('hero-in-temp');
    if (heroInTemp) heroInTemp.textContent = inTempOk ? L.formatNumber(inTempItem.num) + ' °C' : '-';

    var heroOutTemp = $('hero-out-temp');
    if (heroOutTemp) heroOutTemp.textContent = outTempOk ? L.formatNumber(outTempItem.num) + ' °C' : '-';

    var heroSalPair = $('hero-sal-pair');
    if (heroSalPair) {
      var sIn = inSalOk ? L.formatNumber(inSalItem.num) : '-';
      var sOut = outSalOk ? L.formatNumber(outSalItem.num) : '-';
      heroSalPair.textContent = sIn + ' / ' + sOut;
    }

    var diffBadge = $('hero-diff-badge');
    if (diffBadge) {
      diffBadge.className = 'badge ' + st.cls;
      diffBadge.textContent = st.icon + ' ' + st.label;
    }

    var diffValEl = $('hero-diff-value');
    if (diffValEl) {
      diffValEl.textContent = v.diff !== null ? L.formatDiff(v.diff) : '-';
    }

    var measuredEl = $('hero-measured-at');
    if (measuredEl) {
      measuredEl.textContent = metaText(v, now);
    }

    var markerEl = $('hero-spectrum-marker');
    if (markerEl) {
      var pct = 0;
      if (v.diff !== null) {
        pct = Math.max(0, Math.min(100, (Math.max(0, v.diff) / 15) * 100));
      }
      markerEl.style.left = pct.toFixed(1) + '%';
    }
  }

  /* ---- 탭 ---- */
  function renderTabs(vs, code) {
    var nav = $('tabs');
    nav.textContent = '';
    vs.forEach(function (v) {
      var selected = v.code === code;
      var st = STATUS[v.status];
      nav.appendChild(h('button', {
        type: 'button', role: 'tab', class: 'tab', id: 'tab-' + v.code,
        'aria-selected': selected ? 'true' : 'false',
        'aria-label': v.name + ' 본부, ' + st.label,
        onclick: function () { location.hash = v.code; }
      }, v.name, v.status === 'ok' ? null : h('span', { class: 'dot ' + st.cls, 'aria-hidden': 'true', text: st.icon })));
    });
    nav.appendChild(h('button', {
      type: 'button', role: 'tab', class: 'tab tab-all', id: 'tab-ALL',
      'aria-selected': code === 'ALL' ? 'true' : 'false',
      onclick: function () { location.hash = 'ALL'; }
    }, '비교'));
  }

  /* ---- 상세 ---- */
  // 값 문자열이 길면(예: +10.6) 카드 폭에 맞게 글자를 줄인다. 숫자는 줄바꿈하지 않는다.
  function valueClass(text, hasValue) {
    return 'value' + (hasValue ? '' : ' none') + (text.length > 4 ? ' long' : '');
  }

  // 단위(℃)는 섹션 제목과 표 머리글에 표기한다. 값 옆에 붙이면 좁은 화면에서 줄바꿈된다.
  function metric(label, item, now) {
    var showValue = item && !item.stale && item.num !== null;
    var valueText = showValue ? L.formatNumber(item.num) : '-';
    var sub;
    if (!item) sub = '항목 없음';
    else if (item.stale) sub = '최종 수신 ' + L.formatTime(item.time, now);
    else sub = L.formatTime(item.time, now) + ' 기준';
    return h('div', { class: 'metric' },
      h('div', { class: 'label', text: label }),
      h('div', { class: valueClass(valueText, showValue), text: valueText }),
      h('div', { class: 'sub', text: sub }));
  }

  function diffMetric(v) {
    var ok = v.diff !== null;
    return h('div', { class: 'metric diff' },
      h('div', { class: 'label', text: '온도차' }),
      h('div', { class: valueClass(ok ? L.formatDiff(v.diff) : '-', ok), text: ok ? L.formatDiff(v.diff) : '-' }),
      h('div', { class: 'sub', text: ok ? '배수-취수' : '계산 불가' }));
  }

  function metaText(v, now) {
    if (!v.lastReceived) return '수신된 값이 없습니다.';
    var age = L.ageMinutes(v.lastReceived, now);
    if (v.status === 'stale') return '최종 수신 ' + L.formatTime(v.lastReceived, now) + ' (' + L.formatAge(age) + ')';
    return '가장 최근 항목 ' + L.formatTime(v.lastReceived, now) + ' (' + L.formatAge(age) + ')';
  }

  function renderDetail(v, now) {
    var limit = (state.latest && state.latest.stale_after_minutes) || L.DEFAULT_STALE_MINUTES;
    var box = $('detail');
    box.textContent = '';
    var card = h('article', { class: 'card', 'aria-labelledby': 'detail-title' },
      h('div', { class: 'card-head' },
        h('h2', { id: 'detail-title', text: v.name + ' 본부 상세 지표' }),
        badge(v.status)),
      h('p', { class: 'meta', text: metaText(v, now) }));

    if (v.status === 'stale' || v.status === 'nodata') {
      card.appendChild(h('p', { class: 'callout bad', role: 'note' },
        '원천 데이터가 ' + limit + '분 넘게 갱신되지 않아 현재값을 표시하지 않습니다.'));
    } else if (v.status === 'partial') {
      card.appendChild(h('p', { class: 'callout warn', role: 'note' },
        '일부 항목의 시각이 ' + limit + '분을 넘어 해당 항목은 값을 표시하지 않습니다.'));
    } else if (v.status === 'error') {
      card.appendChild(h('p', { class: 'callout warn', role: 'note' },
        '최근 조회에 실패했습니다. 마지막으로 받은 값을 표시합니다.'));
    }

    card.appendChild(h('h3', { class: 'section-title', text: '수온 (°C)' }));
    card.appendChild(h('div', { class: 'metrics' },
      metric('취수구', v.items.inTemp, now),
      metric('배수구', v.items.outTemp, now),
      diffMetric(v)));

    card.appendChild(h('h3', { class: 'section-title', text: '염분' }));
    card.appendChild(h('div', { class: 'metrics two' },
      metric('취수구', v.items.inSal, now),
      metric('배수구', v.items.outSal, now)));

    box.appendChild(card);
  }

  /* ---- 비교 표 ---- */
  function cell(item, now) {
    var ok = item && !item.stale && item.num !== null;
    return h('td', { class: ok ? '' : 'none', text: ok ? L.formatNumber(item.num) : '-' });
  }

  function whenText(v, now) {
    if (!v.lastReceived) return '수신된 값 없음';
    var t = L.formatTime(v.lastReceived, now);
    return (v.status === 'stale' ? '최종 수신 ' : '가장 최근 항목 ') + t;
  }

  function mini(label, item, now, text, isDiff) {
    var ok = text !== undefined ? text !== '-' : (item && !item.stale && item.num !== null);
    var shown = text !== undefined ? text : (ok ? L.formatNumber(item.num) : '-');
    return h('div', { class: 'metric compact' + (isDiff ? ' diff' : '') },
      h('div', { class: 'label', text: label }),
      h('div', { class: 'value' + (ok ? '' : ' none'), text: shown }));
  }

  // 본부별 비교 카드
  function renderCompareCards(vs, now) {
    var box = $('compare-cards');
    box.textContent = '';
    vs.forEach(function (v) {
      box.appendChild(h('article', { class: 'card compare-card' },
        h('div', { class: 'card-head' },
          h('a', { class: 'plant-link', href: '#' + v.code, text: v.name + ' 본부' }),
          badge(v.status)),
        h('p', { class: 'meta', text: whenText(v, now) }),
        h('div', { class: 'metrics' },
          mini('취수구 수온(°C)', v.items.inTemp, now),
          mini('배수구 수온(°C)', v.items.outTemp, now),
          mini('온도차(°C)', null, now, L.formatDiff(v.diff), true)),
        h('div', { class: 'metrics two' },
          mini('취수구 염분', v.items.inSal, now),
          mini('배수구 염분', v.items.outSal, now))));
    });
  }

  function renderCompare(vs, selectedCode, now) {
    renderCompareCards(vs, now);
    var table = $('compare-table');
    table.textContent = '';
    table.appendChild(h('thead', {}, h('tr', {},
      h('th', { scope: 'col', text: '본부' }),
      h('th', { scope: 'col', class: 'status-h', text: '상태' }),
      h('th', { scope: 'col', text: '취수구 수온(°C)' }),
      h('th', { scope: 'col', text: '배수구 수온(°C)' }),
      h('th', { scope: 'col', text: '온도차(°C)' }),
      h('th', { scope: 'col', text: '취수구 염분' }),
      h('th', { scope: 'col', text: '배수구 염분' }),
      h('th', { scope: 'col', class: 'status-h', text: '최근 항목 시각' }))));
    var body = h('tbody');
    vs.forEach(function (v) {
      var when = v.lastReceived ? L.formatTime(v.lastReceived, now) : '-';
      if (v.status === 'stale' && v.lastReceived) when = '최종 수신 ' + when;
      var link = h('a', { class: 'plant-link', href: '#' + v.code, text: v.name });
      body.appendChild(h('tr', { class: v.code === selectedCode ? 'selected' : '' },
        h('th', { scope: 'row' }, link),
        h('td', { class: 'status' }, badge(v.status)),
        cell(v.items.inTemp, now), cell(v.items.outTemp, now),
        h('td', { class: v.diff === null ? 'none' : '', text: L.formatDiff(v.diff) }),
        cell(v.items.inSal, now), cell(v.items.outSal, now),
        h('td', { class: 'when', text: when })));
    });
    table.appendChild(body);
  }

  /* ---- 안내 배너/푸터 ---- */
  function renderNotices(now) {
    var area = $('notice');
    area.textContent = '';
    if (state.loadError) {
      area.appendChild(h('div', { class: 'notice bad' },
        '데이터를 불러오지 못했습니다.' + (state.latest ? ' 마지막으로 받은 값을 표시합니다.' : ''),
        h('button', { type: 'button', onclick: load, text: '다시 시도' })));
    }
    if (navigator.onLine === false) {
      area.appendChild(h('div', { class: 'notice warn' },
        '오프라인 상태입니다. 마지막으로 저장된 값을 표시하며, 시각이 오래된 값은 "수신 중단"으로 표시됩니다.'));
    }
    if (state.fromCache && navigator.onLine !== false) {
      // 서비스 워커가 네트워크 대신 저장본을 돌려준 경우: 수집이 아니라 이 기기의 연결이 문제다.
      area.appendChild(h('div', { class: 'notice warn' },
        '네트워크 연결이 불안정해 이 기기에 저장된 값을 표시하고 있습니다. 연결을 확인한 뒤 새로고침해 주세요. ' +
        '시각이 오래된 값은 "수신 중단"으로 표시됩니다.'));
    }
    if (state.latest && !state.fromCache) {
      var c = L.collectorStatus(state.latest, now);
      if (c.delayed) {
        area.appendChild(h('div', { class: 'notice warn' }, c.known
          ? '자료 수집이 지연되고 있습니다. 마지막 수집 ' + kstString(c.updatedMs) + ' (' + L.formatAge(c.ageMin) +
            '). 표시된 값은 최신이 아닐 수 있습니다.'
          : '자료 수집 시각을 확인할 수 없습니다. 표시된 값은 최신이 아닐 수 있습니다.'));
      }
    }
    var collected = $('collected');
    if (state.latest) {
      var cs = L.collectorStatus(state.latest, now);
      collected.textContent = cs.known
        ? '마지막 수집: ' + kstString(cs.updatedMs) + ' KST (' + L.formatAge(cs.ageMin) + ')'
        : '마지막 수집: 알 수 없음';
    } else {
      collected.textContent = '마지막 수집: -';
    }
  }

  /* ---- 전체 렌더 ---- */
  function render() {
    var now = Date.now();
    $('loading').hidden = !!state.latest || !!state.loadError;
    if (!state.latest) {
      renderNotices(now);
      $('detail').textContent = '';
      window.NPPTrend.update($('trend'), null);
      $('compare').hidden = true;
      return;
    }
    $('compare').hidden = false;
    var code = currentCode();
    var vs = views(now);
    // 넓은 화면은 상세와 비교를 함께 보여주므로 'ALL' 이면 기본 본부를 상세로 둔다.
    var detailCode = code === 'ALL' ? (wide.matches ? DEFAULT_CODE : null) : code;
    document.body.setAttribute('data-view', code === 'ALL' ? 'all' : 'detail');
    renderTabs(vs, wide.matches && code === 'ALL' ? DEFAULT_CODE : code);
    renderHero(vs, detailCode || DEFAULT_CODE, now);
    if (detailCode) {
      var dv = vs.filter(function (v) { return v.code === detailCode; })[0];
      renderDetail(dv, now);
      window.NPPTrend.update($('trend'), {
        code: detailCode, name: dv.name, history: state.history, historyError: state.historyError, now: now
      });
    } else {
      $('detail').textContent = '';
      window.NPPTrend.update($('trend'), null);
    }
    renderCompare(vs, detailCode, now);
    renderNotices(now);
  }

  /* ---- 데이터 로드 ---- */
  function loadHistory(force) {
    if (!force && state.history && Date.now() - state.historyFetchedMs < HISTORY_REFETCH_MS) return Promise.resolve();
    return fetch(HISTORY_URL, { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (json) { state.history = json; state.historyError = false; state.historyFetchedMs = Date.now(); })
      .catch(function () { state.historyError = !state.history; }); // 이전에 받은 이력이 있으면 계속 사용
  }

  // forceHistory === true 이면 이력도 즉시 다시 받는다(새로고침 버튼).
  function load(forceHistory) {
    var historyDone = loadHistory(forceHistory === true);
    return fetch(DATA_URL, { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        state.fromCache = res.headers.get('X-NPP-From-Cache') === '1';   // 서비스 워커가 저장본을 돌려줬는지
        return res.json();
      })
      .then(function (json) {
        state.latest = json;
        state.loadError = null;
        state.lastFetchMs = Date.now();
      })
      .catch(function (err) {
        state.loadError = String(err && err.message || err);
      })
      .then(function () { return historyDone; })
      .then(render);
  }

  window.addEventListener('hashchange', render);
  if (wide.addEventListener) wide.addEventListener('change', render);
  $('refresh').addEventListener('click', function () { load(true); });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && Date.now() - state.lastFetchMs > 2 * 60 * 1000) load();
  });

  /* ---- 설치형 웹앱(PWA) ---- */
  var deferredPrompt = null;

  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  }
  function isIos() {
    var ua = navigator.userAgent || '';
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  }
  function isInAppBrowser() {   // 카카오톡·네이버 등 앱 내 브라우저는 홈 화면 설치를 지원하지 않는다
    return /KAKAOTALK|NAVER\(inapp|; wv\)|FBAN|FBAV|Instagram|Line\//i.test(navigator.userAgent || '');
  }

  function updateInstallUi() {
    var line = $('install-line'), btn = $('install-btn'), hint = $('install-hint');
    line.hidden = true; btn.hidden = true; hint.hidden = true;
    if (isStandalone()) return;                  // 이미 앱으로 실행 중
    if (isInAppBrowser()) {
      hint.textContent = '앱으로 설치하려면 Chrome·삼성 인터넷·Safari 같은 기본 브라우저에서 이 주소를 열어 주세요.';
      hint.hidden = false; line.hidden = false;
    } else if (deferredPrompt) {
      btn.hidden = false; line.hidden = false;
    } else if (isIos()) {
      hint.textContent = '앱처럼 쓰려면 Safari의 공유 버튼에서 "홈 화면에 추가"를 선택하세요.';
      hint.hidden = false; line.hidden = false;
    }
  }

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredPrompt = e;
    updateInstallUi();
  });
  window.addEventListener('appinstalled', function () { deferredPrompt = null; updateInstallUi(); });
  $('install-btn').addEventListener('click', function () {
    if (!deferredPrompt) return;
    var p = deferredPrompt;
    deferredPrompt = null;
    p.prompt();
    Promise.resolve(p.userChoice).then(updateInstallUi, updateInstallUi);
  });
  updateInstallUi();

  if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('./sw.js?data=' + encodeURIComponent(DATA_BASE))
        .catch(function () { /* 설치형 기능만 빠질 뿐 화면은 정상 동작 */ });
    });
  }
  window.addEventListener('online', function () { load(true); });
  window.addEventListener('offline', render);

  setInterval(load, REFETCH_MS);
  setInterval(render, RERENDER_MS);
  load();
})();
