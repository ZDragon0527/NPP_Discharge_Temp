/* 라인 차트(SVG, 외부 라이브러리 없음).
 *
 * 표현 규칙(dataviz 지침)
 *  - 선 2px, 끝점 마커 r=4 + 표면색 2px 링, 격자는 1px 실선·옅게, 값 라벨은 텍스트 색(계열 색 아님)
 *  - 수신 공백(gapMin 초과)은 선을 끊어서 보여준다. 값을 이어 붙이거나 보간하지 않는다.
 *  - 십자선은 가장 가까운 데이터 시각에 붙고, 툴팁은 모든 계열의 값을 함께 보여준다(값이 먼저, 이름은 뒤).
 *  - 툴팁은 보조 수단: 같은 값을 끝점 라벨과 '표로 보기'에서도 읽을 수 있고, 키보드 좌우 화살표로도 같은 정보를 본다.
 *  - 값·이름은 textContent 로만 넣는다(innerHTML 사용 안 함).
 */
(function (root) {
  'use strict';

  var L = root.NPP;
  var SVGNS = 'http://www.w3.org/2000/svg';
  var M = { t: 14, r: 34, b: 26, l: 32 };    // 여백: 오른쪽은 끝점 라벨, 왼쪽은 y 눈금
  var LABEL_GAP = 14;                       // 끝점 라벨 사이 최소 간격(px)

  function svg(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }

  function html(tag, cls, parent, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  /**
   * spec.container   차트를 넣을 요소
   * spec.series      [{ key, name, color('var(--s1)' 등), points: [[t, v], ...] }] (시각순)
   * spec.startMin / endMin  x 축 범위(epoch 분)
   * spec.gapMin      이 분을 넘게 비면 선을 끊음
   * spec.decimals    값 표기 소수 자릿수(기본 1)
   * spec.area        단일 계열일 때 면 채움(10%)
   * spec.sampleNote  툴팁 시각 옆 보조 설명(예: '1시간 평균')
   * spec.ariaLabel   차트 설명
   * spec.height      높이(px, 기본 210)
   * spec.minSpan     y 축 최소 폭. 값 범위가 이보다 좁으면 가운데를 기준으로 넓혀,
   *                 아주 작은 변동(예: 0.1°C)이 급격한 변화처럼 보이지 않게 한다.
   */
  function render(spec) {
    var container = spec.container;
    container.textContent = '';
    var series = spec.series.filter(function (s) { return s.points && s.points.length; });
    var decimals = spec.decimals === undefined ? 1 : spec.decimals;
    function fmt(v) { return v === null || v === undefined ? '—' : v.toFixed(decimals); }

    if (!series.length) {
      html('p', 'chart-empty', container, spec.emptyText || '선택한 기간에 저장된 값이 없습니다.');
      return { destroy: function () {} };
    }

    var W = Math.max(260, spec.width || container.clientWidth || 320);
    var H = spec.height || (W < 640 ? 125 : 210);
    var pw = W - M.l - M.r, ph = H - M.t - M.b;
    var start = spec.startMin, end = spec.endMin;

    // y 축 범위: 값 범위 + 8% 여백 → 깔끔한 눈금
    var lo = Infinity, hi = -Infinity;
    series.forEach(function (s) { s.points.forEach(function (p) { if (p[1] < lo) lo = p[1]; if (p[1] > hi) hi = p[1]; }); });
    var minSpan = spec.minSpan || 0;
    if (hi - lo < minSpan) { var center = (hi + lo) / 2; lo = center - minSpan / 2; hi = center + minSpan / 2; }
    var pad = (hi - lo) * 0.08 || 0.5;
    var yt = L.niceTicks(lo - pad, hi + pad, 4);
    function x(t) { return M.l + (t - start) / (end - start) * pw; }
    function y(v) { return M.t + ph - (v - yt.min) / (yt.max - yt.min) * ph; }

    var wrap = html('div', 'chart-inner', container);
    wrap.setAttribute('tabindex', '0');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', (spec.ariaLabel || '추이 차트') + ' 좌우 화살표 키로 값을 확인할 수 있습니다.');

    var el = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, class: 'chart-svg', 'aria-hidden': 'true', focusable: 'false' }, wrap);

    // 격자 + y 눈금 (1px 실선, 눈금 라벨은 보조 텍스트색)
    yt.ticks.forEach(function (v) {
      var yy = y(v);
      svg('line', { x1: M.l, x2: W - M.r, y1: yy, y2: yy, class: v === yt.min ? 'axis-line' : 'grid-line' }, el);
      svg('text', { x: M.l - 6, y: yy, dy: '.35em', 'text-anchor': 'end', class: 'tick-label' }, el).textContent = v.toFixed(yt.decimals);
    });

    // x 눈금
    var xt = L.xTicks(start, end, pw, 52);
    xt.ticks.forEach(function (t) {
      var xx = x(t.t);
      svg('line', { x1: xx, x2: xx, y1: M.t + ph, y2: M.t + ph + 4, class: 'axis-line' }, el);
      var anchor = xx < M.l + 14 ? 'start' : xx > W - 24 ? 'end' : 'middle';
      svg('text', { x: xx, y: M.t + ph + 17, 'text-anchor': anchor, class: 'tick-label' }, el).textContent = t.label;
    });

    // 면(단일 계열) → 선 → 외톨이 점 순서
    var single = series.length === 1 && spec.area;
    series.forEach(function (s) {
      var segs = L.splitSegments(s.points, spec.gapMin);
      segs.forEach(function (seg) {
        if (seg.length < 2) {
          svg('circle', { cx: x(seg[0][0]), cy: y(seg[0][1]), r: 4, fill: s.color, class: 'dot-ring' }, el);
          return;
        }
        var d = seg.map(function (p, i) { return (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ' ' + y(p[1]).toFixed(1); }).join('');
        if (single) {
          svg('path', {
            d: d + 'L' + x(seg[seg.length - 1][0]).toFixed(1) + ' ' + (M.t + ph) + 'L' + x(seg[0][0]).toFixed(1) + ' ' + (M.t + ph) + 'Z',
            fill: s.color, 'fill-opacity': '0.10', stroke: 'none'
          }, el);
        }
        svg('path', { d: d, fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, el);
      });
    });

    // 끝점: 마커 + 값 라벨(텍스트색). 라벨이 겹치면 위아래로 벌린다(2계열 기준, 점 바로 옆에 유지).
    var ends = series.map(function (s) {
      var p = s.points[s.points.length - 1];
      return { s: s, px: x(p[0]), py: y(p[1]), ly: y(p[1]), v: p[1] };
    }).sort(function (a, b) { return a.py - b.py; });
    for (var i = 1; i < ends.length; i++) {
      var gap = ends[i].ly - ends[i - 1].ly;
      if (gap < LABEL_GAP) {
        var mid = (ends[i].ly + ends[i - 1].ly) / 2;
        ends[i - 1].ly = mid - LABEL_GAP / 2;
        ends[i].ly = mid + LABEL_GAP / 2;
      }
    }
    ends.forEach(function (e) {
      svg('circle', { cx: e.px, cy: e.py, r: 4, fill: e.s.color, class: 'dot-ring' }, el);
      var anchor = e.px + 8 + 34 > W ? 'end' : 'start';
      svg('text', { x: anchor === 'start' ? e.px + 8 : e.px - 8, y: e.ly, dy: '.35em', 'text-anchor': anchor, class: 'end-label' }, el).textContent = fmt(e.v);
    });

    // ---- 호버/포커스 레이어 ----
    var cross = svg('line', { y1: M.t, y2: M.t + ph, class: 'crosshair', visibility: 'hidden' }, el);
    var hoverDots = series.map(function (s) {
      return svg('circle', { r: 4, fill: s.color, class: 'dot-ring', visibility: 'hidden' }, el);
    });
    var hit = svg('rect', { x: M.l, y: M.t, width: pw, height: ph, fill: 'transparent', class: 'chart-hit' }, el);

    var tip = html('div', 'chart-tip', wrap);
    tip.setAttribute('aria-hidden', 'true');
    tip.style.display = 'none';
    var live = html('div', 'sr-only', wrap);
    live.setAttribute('aria-live', 'polite');

    var tol = Math.max(10, spec.gapMin / 2);
    var anchorSeries = series.slice().sort(function (a, b) { return b.points.length - a.points.length; })[0];
    var cursorIdx = -1;

    function showAt(t) {
      var xx = x(t);
      cross.setAttribute('x1', xx); cross.setAttribute('x2', xx); cross.setAttribute('visibility', 'visible');
      tip.textContent = '';
      html('div', 'tip-time', tip, L.formatKstFull(t) + (spec.sampleNote ? ' · ' + spec.sampleNote : ''));
      var summary = [L.formatKstFull(t)];
      series.forEach(function (s, i) {
        var n = L.nearestIndex(s.points, t);
        var ok = n >= 0 && Math.abs(s.points[n][0] - t) <= tol;
        var row = html('div', 'tip-row', tip);
        var key = html('span', 'tip-key', row);
        key.style.borderTopColor = s.color;
        html('span', 'tip-val', row, ok ? fmt(s.points[n][1]) : '—');
        html('span', 'tip-name', row, s.name);
        if (ok) {
          hoverDots[i].setAttribute('cx', x(s.points[n][0])); hoverDots[i].setAttribute('cy', y(s.points[n][1]));
          hoverDots[i].setAttribute('visibility', 'visible');
        } else {
          hoverDots[i].setAttribute('visibility', 'hidden');
        }
        summary.push(s.name + ' ' + (ok ? fmt(s.points[n][1]) : '값 없음'));
      });
      tip.style.display = 'block';
      var tw = tip.offsetWidth;
      var left = xx + 12 + tw > W ? xx - 12 - tw : xx + 12;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = (M.t + 2) + 'px';
      return summary.join(', ');
    }

    function hide() {
      cross.setAttribute('visibility', 'hidden');
      hoverDots.forEach(function (d) { d.setAttribute('visibility', 'hidden'); });
      tip.style.display = 'none';
    }

    // 포인터가 가리키는 시각에서 가장 가까운 데이터 시각(모든 계열 중)으로 붙인다.
    function nearestTime(px) {
      var rect = el.getBoundingClientRect();
      var t = start + ((px - rect.left) * (W / rect.width) - M.l) / pw * (end - start);
      var best = null;
      series.forEach(function (s) {
        var n = L.nearestIndex(s.points, t);
        if (n >= 0 && (best === null || Math.abs(s.points[n][0] - t) < Math.abs(best - t))) best = s.points[n][0];
      });
      return best;
    }

    function onPointer(ev) {
      var t = nearestTime(ev.clientX);
      if (t !== null) {
        showAt(t);
        cursorIdx = Math.max(0, L.nearestIndex(anchorSeries.points, t));
      }
    }
    hit.style.touchAction = 'pan-y';   // 세로 스크롤은 허용하고 가로 드래그로 값을 훑는다
    hit.addEventListener('pointerdown', onPointer);
    hit.addEventListener('pointermove', onPointer);
    hit.addEventListener('pointerleave', function (ev) { if (ev.pointerType === 'mouse') hide(); });

    wrap.addEventListener('focus', function () {
      cursorIdx = anchorSeries.points.length - 1;
      live.textContent = showAt(anchorSeries.points[cursorIdx][0]);
    });
    wrap.addEventListener('blur', hide);
    wrap.addEventListener('keydown', function (ev) {
      var n = anchorSeries.points.length;
      if (ev.key === 'ArrowLeft') cursorIdx = Math.max(0, (cursorIdx < 0 ? n - 1 : cursorIdx) - 1);
      else if (ev.key === 'ArrowRight') cursorIdx = Math.min(n - 1, (cursorIdx < 0 ? n - 1 : cursorIdx) + 1);
      else if (ev.key === 'Home') cursorIdx = 0;
      else if (ev.key === 'End') cursorIdx = n - 1;
      else if (ev.key === 'Escape') { hide(); return; }
      else return;
      ev.preventDefault();
      live.textContent = showAt(anchorSeries.points[cursorIdx][0]);
    });

    return { destroy: function () { container.textContent = ''; } };
  }

  root.NPPChart = { render: render };
})(typeof globalThis !== 'undefined' ? globalThis : this);
