/* 화면 로직(순수 함수). DOM에 의존하지 않아 Node 에서도 테스트한다.
 *
 * 원칙
 *  - 오래된 값은 현재값처럼 보이지 않게 한다. 오래됨 여부는 "지금(viewer 시각)" 기준으로 다시 계산한다.
 *    (수집기가 멈춰도 latest.json 의 stale 플래그는 갱신되지 않으므로 서버 플래그를 믿지 않는다.)
 *  - 판단 문구(정상/이상 등)를 만들지 않는다. 수신 상태와 수치만 다룬다.
 */
(function (root) {
  'use strict';

  var KST_OFFSET_MS = 9 * 3600 * 1000;
  var DEFAULT_STALE_MINUTES = 60;   // 확정: 항목 시각이 60분 초과 경과 시 수신 중단/지연
  var COLLECT_DELAY_MINUTES = 30;   // 수집 간격(10분)의 3배. 이 시간 넘게 수집 기록이 없으면 안내 배너

  var PLANTS = [
    { code: 'WS', name: '월성' },
    { code: 'KR', name: '고리' },
    { code: 'YK', name: '한빛' },
    { code: 'UJ', name: '한울' }
  ];

  // API 응답의 expl 문자열 → 화면 항목 키
  var ITEM_KEYS = {
    '취수구-수온': 'inTemp',
    '배수구-수온': 'outTemp',
    '취수구-염분': 'inSal',
    '배수구-염분': 'outSal'
  };

  /** "YYYY-MM-DD HH:MM"(KST) → epoch ms. 해석 불가면 null. */
  function parseKst(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(s || '');
    if (!m) return null;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) - KST_OFFSET_MS;
  }

  function ageMinutes(timeStr, nowMs) {
    var t = parseKst(timeStr);
    return t === null ? null : Math.floor((nowMs - t) / 60000);
  }

  function isStale(age, limit) {
    return age === null || age > limit;
  }

  function parseValue(s) {
    if (s === null || s === undefined || String(s).trim() === '') return null;
    var n = Number(s);
    return isFinite(n) ? n : null;
  }

  /** 본부 하나의 화면용 데이터. */
  function buildPlantView(code, plant, nowMs, limit) {
    limit = limit || DEFAULT_STALE_MINUTES;
    var meta = PLANTS.filter(function (p) { return p.code === code; })[0] || { name: code };
    var view = {
      code: code,
      name: (plant && plant.name) || meta.name,
      items: {},
      status: 'nodata',      // ok | partial | stale | error | nodata
      callError: (plant && plant.error) || null,
      lastReceivedMs: null,  // 가장 최근 항목 시각
      lastReceived: null,
      diff: null
    };
    var list = (plant && plant.items) || [];
    var staleCount = 0;
    list.forEach(function (it) {
      var key = ITEM_KEYS[it.expl];
      if (!key) return;
      var age = ageMinutes(it.time, nowMs);
      var stale = isStale(age, limit);
      if (stale) staleCount++;
      var t = parseKst(it.time);
      if (t !== null && (view.lastReceivedMs === null || t > view.lastReceivedMs)) {
        view.lastReceivedMs = t;
        view.lastReceived = it.time;
      }
      view.items[key] = { expl: it.expl, time: it.time, age: age, stale: stale, num: parseValue(it.value), raw: it.value };
    });
    var count = Object.keys(view.items).length;
    if (count === 0) {
      view.status = 'nodata';
    } else if (staleCount === count) {
      view.status = 'stale';
    } else if (staleCount > 0) {
      view.status = 'partial';
    } else if (view.callError) {
      view.status = 'error';
    } else {
      view.status = 'ok';
    }
    var a = view.items.inTemp, b = view.items.outTemp;
    if (a && b && !a.stale && !b.stale && a.num !== null && b.num !== null) {
      view.diff = Math.round((b.num - a.num) * 10) / 10;
    }
    return view;
  }

  /** 수집기 자체가 멈췄는지(latest.json 의 갱신 시각 기준). */
  function collectorStatus(latest, nowMs) {
    var t = latest && latest.updated_at_utc ? Date.parse(latest.updated_at_utc) : NaN;
    if (isNaN(t)) return { known: false, delayed: true, ageMin: null, updatedMs: null };
    var age = Math.floor((nowMs - t) / 60000);
    return { known: true, delayed: age > COLLECT_DELAY_MINUTES, ageMin: age, updatedMs: t };
  }

  function formatAge(min) {
    if (min === null || min === undefined) return '';
    if (min < 1) return '방금';
    if (min < 60) return min + '분 전';
    var h = Math.floor(min / 60), m = min % 60;
    if (h < 24) return m ? h + '시간 ' + m + '분 전' : h + '시간 전';
    var d = Math.floor(h / 24), hh = h % 24;
    return hh ? d + '일 ' + hh + '시간 전' : d + '일 전';
  }

  /** KST 기준 오늘 날짜(YYYY-MM-DD). */
  function kstDate(nowMs) {
    return new Date(nowMs + KST_OFFSET_MS).toISOString().slice(0, 10);
  }

  /** 오늘이면 HH:MM, 아니면 YYYY-MM-DD HH:MM. */
  function formatTime(timeStr, nowMs) {
    if (!timeStr) return '-';
    if (timeStr.slice(0, 10) === kstDate(nowMs)) return timeStr.slice(11);
    return timeStr;
  }

  function formatNumber(n) {
    return n === null ? '—' : n.toFixed(1);
  }

  function formatDiff(n) {
    if (n === null) return '—';
    var s = Math.abs(n).toFixed(1);
    return (n > 0 ? '+' : n < 0 ? '−' : '') + s;
  }

  /* ================= 추이 차트용 순수 함수 =================
   * 시각은 모두 "UTC 기준 epoch 분"(history.json 과 동일). 화면 표기는 KST. */

  // 24시간은 원본(raw), 7일·30일은 1시간 평균(hourly). gap: 이 분을 넘게 비면 선을 끊는다.
  //  - raw: 60분(= 수신 중단 기준과 동일)
  //  - hourly: 120분(연속 2시간 이상 비어 있을 때만 끊음)
  var RANGES = [
    { key: '24h', label: '24시간', minutes: 24 * 60, source: 'raw', gap: 60, note: '원본 값' },
    { key: '7d', label: '7일', minutes: 7 * 24 * 60, source: 'hourly', gap: 120, note: '1시간 평균' },
    { key: '30d', label: '30일', minutes: 30 * 24 * 60, source: 'hourly', gap: 120, note: '1시간 평균' }
  ];

  function rangeByKey(key) {
    return RANGES.filter(function (r) { return r.key === key; })[0] || RANGES[0];
  }

  function niceNum(range, round) {
    var exp = Math.floor(Math.log(range) / Math.LN10);
    var f = range / Math.pow(10, exp);
    var nf;
    if (round) nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10;
    else nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
    return nf * Math.pow(10, exp);
  }

  /** 데이터 범위 → 깔끔한 y 축 눈금. 값이 하나뿐이거나 평평하면 ±0.5 로 넓힌다. */
  function niceTicks(min, max, target) {
    target = target || 4;
    if (!(max > min)) { var c = min; min = c - 0.5; max = c + 0.5; }
    var step = niceNum(niceNum(max - min, false) / target, true);
    var lo = Math.floor(min / step + 1e-9) * step;
    var hi = Math.ceil(max / step - 1e-9) * step;
    var decimals = Math.max(0, -Math.floor(Math.log(step) / Math.LN10 + 1e-9));
    var n = Math.round((hi - lo) / step);
    var ticks = [];
    for (var i = 0; i <= n; i++) ticks.push(Number((lo + i * step).toFixed(decimals)));
    return { min: ticks[0], max: ticks[ticks.length - 1], ticks: ticks, step: step, decimals: decimals };
  }

  /** 시각순 [[t, v], ...] 를 gapMin 분을 넘게 비는 곳에서 잘라 구간 배열로 만든다. */
  function splitSegments(points, gapMin) {
    var segs = [], cur = null;
    for (var i = 0; i < points.length; i++) {
      if (cur && points[i][0] - cur[cur.length - 1][0] > gapMin) cur = null;
      if (!cur) { cur = []; segs.push(cur); }
      cur.push(points[i]);
    }
    return segs;
  }

  /** 시각이 가장 가까운 점의 인덱스(없으면 -1). points 는 시각순. */
  function nearestIndex(points, t) {
    var n = points.length;
    if (!n) return -1;
    var lo = 0, hi = n - 1;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (points[mid][0] < t) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(points[lo - 1][0] - t) <= Math.abs(points[lo][0] - t)) lo--;
    return lo;
  }

  function windowPoints(points, startMin, endMin) {
    return (points || []).filter(function (p) { return p[0] >= startMin && p[0] <= endMin; });
  }

  /** 두 계열을 시각이 tol 분 이내인 것끼리 짝지어 (b − a) 계열을 만든다. 소수 첫째 자리로 반올림. */
  function diffSeries(aPts, bPts, tol) {
    var out = [];
    bPts.forEach(function (b) {
      var i = nearestIndex(aPts, b[0]);
      if (i < 0 || Math.abs(aPts[i][0] - b[0]) > tol) return;
      out.push([b[0], Math.round((b[1] - aPts[i][1]) * 10) / 10]);
    });
    return out;
  }

  function kstParts(tMin) {
    var d = new Date((tMin + 540) * 60000);
    function p(n) { return n < 10 ? '0' + n : '' + n; }
    return { y: d.getUTCFullYear(), mo: p(d.getUTCMonth() + 1), d: p(d.getUTCDate()), h: p(d.getUTCHours()), mi: p(d.getUTCMinutes()) };
  }

  function formatKstFull(tMin) {
    var k = kstParts(tMin);
    return k.y + '-' + k.mo + '-' + k.d + ' ' + k.h + ':' + k.mi;
  }

  /** x 축 눈금: KST 기준 정렬, 라벨 간격이 minLabelPx 이상 되도록 간격을 고른다. */
  function xTicks(startMin, endMin, widthPx, minLabelPx) {
    var steps = [60, 120, 180, 360, 720, 1440, 2880, 7200, 10080];
    var span = endMin - startMin;
    var step = steps[steps.length - 1];
    for (var i = 0; i < steps.length; i++) {
      if ((span / steps[i]) * minLabelPx <= widthPx) { step = steps[i]; break; }
    }
    var first = Math.ceil((startMin + 540) / step) * step - 540;
    var ticks = [];
    for (var t = first; t <= endMin; t += step) {
      var k = kstParts(t);
      var label = step >= 1440 ? k.mo + '/' + k.d : (k.h === '00' ? k.mo + '/' + k.d : k.h + ':' + k.mi);
      ticks.push({ t: t, label: label });
    }
    return { step: step, ticks: ticks };
  }

  /** 표 보기용: anchor 계열의 시각을 (최대 maxRows 개로 고르게 줄여) 행으로 삼고 다른 계열은 가장 가까운 값을 붙인다. */
  function alignRows(seriesMap, anchorKey, maxRows, tol) {
    var anchor = seriesMap[anchorKey] || [];
    var idx = [];
    if (anchor.length <= maxRows) {
      for (var i = 0; i < anchor.length; i++) idx.push(i);
    } else {
      for (var j = 0; j < maxRows; j++) idx.push(Math.round(j * (anchor.length - 1) / (maxRows - 1)));
    }
    var rows = idx.map(function (ix) {
      var t = anchor[ix][0], vals = {};
      Object.keys(seriesMap).forEach(function (k) {
        var pts = seriesMap[k] || [];
        var n = nearestIndex(pts, t);
        vals[k] = n >= 0 && Math.abs(pts[n][0] - t) <= tol ? pts[n][1] : null;
      });
      return { t: t, vals: vals };
    });
    rows.reverse(); // 최신순
    return rows;
  }

  var api = {
    RANGES: RANGES,
    rangeByKey: rangeByKey,
    niceTicks: niceTicks,
    splitSegments: splitSegments,
    nearestIndex: nearestIndex,
    windowPoints: windowPoints,
    diffSeries: diffSeries,
    formatKstFull: formatKstFull,
    xTicks: xTicks,
    alignRows: alignRows,
    PLANTS: PLANTS,
    DEFAULT_STALE_MINUTES: DEFAULT_STALE_MINUTES,
    COLLECT_DELAY_MINUTES: COLLECT_DELAY_MINUTES,
    parseKst: parseKst,
    ageMinutes: ageMinutes,
    isStale: isStale,
    parseValue: parseValue,
    buildPlantView: buildPlantView,
    collectorStatus: collectorStatus,
    formatAge: formatAge,
    kstDate: kstDate,
    formatTime: formatTime,
    formatNumber: formatNumber,
    formatDiff: formatDiff
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.NPP = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
