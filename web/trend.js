/* 추이 영역: 기간 선택(24시간/7일/30일) + 차트 3개(수온·온도차·염분) + 표 보기.
 * 차트마다 y 축이 하나이고, 서로 다른 단위·규모는 별도 차트로 나눈다(이중 축 사용 안 함).
 * 색은 항목에 고정: 취수구=--s1(파랑), 배수구=--s2(주황), 온도차=--s3(아쿠아). */
(function (root) {
  'use strict';

  var L = root.NPP;
  var C = root.NPPChart;
  var TABLE_ROWS = 48;
  var Y_MIN_SPAN = 2;   // y 축 최소 폭(°C 또는 염분 단위). 미세한 변동이 과장되어 보이지 않게 한다.
  var state = { range: '24h', ctx: null, container: null, resizeTimer: null };

  function h(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function legend(items) {
    var ul = h('ul', 'legend');
    items.forEach(function (it) {
      var li = h('li');
      var key = h('span', 'legend-key');
      key.style.borderTopColor = it.color;
      li.appendChild(key);
      li.appendChild(document.createTextNode(it.name));
      ul.appendChild(li);
    });
    return ul;
  }

  function chartBlock(title, subtitle, legendItems) {
    var fig = h('figure', 'chart-block');
    var cap = h('figcaption');
    cap.appendChild(h('h3', 'chart-title', title));
    if (subtitle) cap.appendChild(h('span', 'chart-sub', subtitle));
    if (legendItems.length >= 2) cap.appendChild(legend(legendItems));   // 계열이 2개 이상일 때만 범례
    fig.appendChild(cap);
    var wrap = h('div', 'chart-wrap');
    fig.appendChild(wrap);
    return { fig: fig, wrap: wrap };
  }

  function tableView(seriesMap, rng) {
    var details = h('details', 'table-view');
    details.appendChild(h('summary', '', '표로 보기'));
    var anchor = ['outTemp', 'inTemp', 'outSal', 'inSal'].filter(function (k) { return (seriesMap[k] || []).length; })[0];
    if (!anchor) { details.appendChild(h('p', 'meta', '표시할 값이 없습니다.')); return details; }
    var tol = rng.source === 'raw' ? 5 : 0;
    var rows = L.alignRows(seriesMap, anchor, TABLE_ROWS, tol);
    var cols = [['inTemp', '취수구 수온(°C)'], ['outTemp', '배수구 수온(°C)'], ['diff', '온도차(°C)'], ['inSal', '취수구 염분'], ['outSal', '배수구 염분']];
    var scroll = h('div', 'table-wrap table-wrap-inline');
    scroll.setAttribute('tabindex', '0');
    scroll.setAttribute('role', 'region');
    scroll.setAttribute('aria-label', '추이 값 표(좌우로 스크롤)');
    var table = h('table', 'trend-table');
    var thead = h('thead'); var hr = h('tr');
    var th0 = h('th', '', '시각(KST)'); th0.setAttribute('scope', 'col'); hr.appendChild(th0);
    cols.forEach(function (c) { var th = h('th', '', c[1]); th.setAttribute('scope', 'col'); hr.appendChild(th); });
    thead.appendChild(hr); table.appendChild(thead);
    var tbody = h('tbody');
    rows.forEach(function (r) {
      var tr = h('tr');
      var th = h('th', '', L.formatKstFull(r.t)); th.setAttribute('scope', 'row'); tr.appendChild(th);
      cols.forEach(function (c) {
        var v = r.vals[c[0]];
        tr.appendChild(h('td', v === null || v === undefined ? 'none' : '', v === null || v === undefined ? '—' : v.toFixed(1)));
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    details.appendChild(scroll);
    details.appendChild(h('p', 'meta', '전체 ' + (seriesMap[anchor] || []).length + '개 중 최대 ' + TABLE_ROWS + '개 시각을 고르게 골라 최신순으로 표시합니다.'));
    return details;
  }

  function build(container, ctx) {
    var history = ctx.history;
    container.textContent = '';
    var card = h('article', 'card trend');
    card.setAttribute('aria-labelledby', 'trend-title');
    var head = h('div', 'card-head');
    var title = h('h2', '', ctx.name + '본부 추이');
    title.id = 'trend-title';
    head.appendChild(title);

    // 기간 선택: 차트 위 한 줄(차트 카드 안이 아니라 추이 영역 머리)
    var group = h('div', 'range');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', '기간 선택');
    L.RANGES.forEach(function (r) {
      var b = h('button', 'range-btn', r.label);
      b.type = 'button';
      b.setAttribute('aria-pressed', r.key === state.range ? 'true' : 'false');
      b.addEventListener('click', function () {
        if (state.range === r.key) return;
        state.range = r.key;
        container.removeAttribute('data-sig');
        update(container, state.ctx);
      });
      group.appendChild(b);
    });
    head.appendChild(group);
    card.appendChild(head);
    container.appendChild(card);

    if (!history) {
      card.appendChild(h('p', 'meta', ctx.historyError ? '추이 이력을 불러오지 못했습니다.' : '추이 이력을 불러오는 중…'));
      return;
    }

    var rng = L.rangeByKey(state.range);
    var endMin = Math.floor(ctx.now / 60000);
    var startFull = endMin - rng.minutes;
    var firstT = history.first_t;
    var startMin = firstT !== null && firstT !== undefined ? Math.max(startFull, firstT) : startFull;
    if (endMin - startMin < 60) startMin = endMin - 60;   // 수집 직후에도 최소 1시간 폭

    var plant = (history.plants && history.plants[ctx.code]) || {};
    function pts(key) { return L.windowPoints((plant[key] || {})[rng.source], startMin, endMin); }
    var inT = pts('inTemp'), outT = pts('outTemp'), inS = pts('inSal'), outS = pts('outSal');
    var diff = L.diffSeries(inT, outT, rng.source === 'raw' ? 5 : 0);

    var notes = [];
    if (firstT !== null && firstT !== undefined && firstT > startFull + 30) {
      notes.push('수집은 ' + L.formatKstFull(firstT) + '(KST)부터 시작되어 그 이후 구간만 표시합니다.');
    }
    notes.push(rng.source === 'hourly' ? '이 기간은 1시간 평균값입니다.' : '수집된 원본 값입니다.');
    notes.push('선이 끊긴 구간은 값이 수신·저장되지 않은 구간입니다(값을 이어 그리지 않습니다).');
    card.appendChild(h('p', 'meta trend-note', notes.join(' ')));

    var allEmpty = !inT.length && !outT.length && !inS.length && !outS.length;
    if (allEmpty) {
      card.appendChild(h('p', 'callout', '선택한 기간에 저장된 값이 없습니다.'));
      return;
    }

    var S1 = 'var(--s1)', S2 = 'var(--s2)', S3 = 'var(--s3)';
    var grid = h('div', 'charts');
    var blocks = [
      { title: '수온 (°C)', sub: '', series: [
          { key: 'inTemp', name: '취수구', color: S1, points: inT },
          { key: 'outTemp', name: '배수구', color: S2, points: outT }], area: false,
        label: ctx.name + '본부 취수구와 배수구 수온 추이' },
      { title: '온도차 (°C)', sub: '배수구−취수구', series: [
          { key: 'diff', name: '온도차', color: S3, points: diff }], area: true,
        label: ctx.name + '본부 취수구와 배수구 수온의 차이 추이' },
      { title: '염분', sub: '', series: [
          { key: 'inSal', name: '취수구', color: S1, points: inS },
          { key: 'outSal', name: '배수구', color: S2, points: outS }], area: false,
        label: ctx.name + '본부 취수구와 배수구 염분 추이' }
    ];
    var made = blocks.map(function (b) {
      var present = b.series.filter(function (s) { return s.points.length; });
      var blk = chartBlock(b.title, b.sub, present.length >= 2 ? present : []);
      grid.appendChild(blk.fig);
      return { b: b, wrap: blk.wrap };
    });
    card.appendChild(grid);   // 폭 측정을 위해 DOM 에 붙인 뒤 그린다
    made.forEach(function (m) {
      C.render({
        container: m.wrap, series: m.b.series, startMin: startMin, endMin: endMin, gapMin: rng.gap,
        decimals: 1, area: m.b.area, ariaLabel: m.b.label, minSpan: Y_MIN_SPAN,
        sampleNote: rng.source === 'hourly' ? '1시간 평균' : '',
        emptyText: '선택한 기간에 이 항목의 값이 없습니다.'
      });
    });

    card.appendChild(tableView({ inTemp: inT, outTemp: outT, diff: diff, inSal: inS, outSal: outS }, rng));
  }

  /** 같은 입력이면 다시 그리지 않는다(60초마다 도는 화면 갱신에서 호버 상태가 사라지지 않게). */
  function update(container, ctx) {
    state.ctx = ctx;
    state.container = container;
    if (!ctx) { container.textContent = ''; container.removeAttribute('data-sig'); return; }
    var sig = [ctx.code, state.range, ctx.history ? ctx.history.generated_at_utc : '-', ctx.historyError ? 1 : 0,
      Math.floor(ctx.now / 600000), container.clientWidth].join('|');
    if (container.getAttribute('data-sig') === sig) return;
    container.setAttribute('data-sig', sig);
    build(container, ctx);
  }

  window.addEventListener('resize', function () {
    clearTimeout(state.resizeTimer);
    state.resizeTimer = setTimeout(function () {
      if (state.container && state.ctx) update(state.container, state.ctx);
    }, 150);
  });

  root.NPPTrend = { update: update, getRange: function () { return state.range; } };
})(typeof globalThis !== 'undefined' ? globalThis : this);
