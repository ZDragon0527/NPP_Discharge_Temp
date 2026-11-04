const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const L = require('../web/logic.js');

const sample = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'latest.sample.json'), 'utf8'));
// 2026-11-04 15:00 KST = 06:00 UTC
const NOW = Date.UTC(2026, 10, 4, 6, 0);

test('parseKst: KST 문자열을 epoch 로 변환, 잘못된 형식은 null', () => {
  assert.equal(L.parseKst('2026-11-04 15:00'), NOW);
  assert.equal(L.parseKst('bad'), null);
  assert.equal(L.parseKst(''), null);
  assert.equal(L.parseKst(undefined), null);
});

test('isStale: 60분은 정상, 61분과 해석 불가는 오래됨', () => {
  assert.equal(L.isStale(60, 60), false);
  assert.equal(L.isStale(61, 60), true);
  assert.equal(L.isStale(null, 60), true);
});

test('월성: 최신 수신 → ok, 온도차 = 배수구-취수구', () => {
  const v = L.buildPlantView('WS', sample.plants.WS, NOW);
  assert.equal(v.status, 'ok');
  assert.equal(v.items.inTemp.num, 19.2);
  assert.equal(v.items.outTemp.num, 22.9);
  assert.equal(v.diff, 3.7); // 22.9 - 19.2
});

test('고리: 4개월 전 값 → stale, 온도차 없음, 최종 수신 시각 유지', () => {
  const v = L.buildPlantView('KR', sample.plants.KR, NOW);
  assert.equal(v.status, 'stale');
  assert.equal(v.diff, null);
  assert.equal(v.lastReceived, '2026-07-07 10:19');
  assert.ok(Object.values(v.items).every((i) => i.stale));
});

test('서버 stale 플래그가 아니라 현재 시각 기준으로 다시 판단한다', () => {
  // 수집기가 멈춰 3시간이 지난 상황: 같은 데이터라도 이제 stale
  const later = NOW + 3 * 3600 * 1000;
  const v = L.buildPlantView('WS', sample.plants.WS, later);
  assert.equal(v.status, 'stale');
});

test('일부 항목만 오래됨 → partial, 온도차는 두 수온이 모두 최신일 때만', () => {
  const plant = {
    name: '테스트', error: null,
    items: [
      { expl: '취수구-수온', time: '2026-11-04 14:50', value: '10.0' },
      { expl: '배수구-수온', time: '2026-11-04 10:00', value: '14.0' },
      { expl: '취수구-염분', time: '2026-11-04 14:50', value: '30.0' },
      { expl: '배수구-염분', time: '2026-11-04 14:50', value: '31.0' }
    ]
  };
  const v = L.buildPlantView('WS', plant, NOW);
  assert.equal(v.status, 'partial');
  assert.equal(v.diff, null);
});

test('호출 오류가 있고 값은 최신 → error 상태(값은 유지)', () => {
  const plant = { name: '월성', error: 'HTTP 500', items: sample.plants.WS.items };
  const v = L.buildPlantView('WS', plant, NOW);
  assert.equal(v.status, 'error');
  assert.equal(v.callError, 'HTTP 500');
  assert.equal(v.items.inTemp.num, 19.2);
});

test('항목이 없으면 nodata', () => {
  assert.equal(L.buildPlantView('WS', { name: '월성', items: [] }, NOW).status, 'nodata');
  assert.equal(L.buildPlantView('WS', undefined, NOW).status, 'nodata');
});

test('빈 값/숫자 아님은 num=null, 온도차 없음', () => {
  const plant = {
    name: '월성',
    items: [
      { expl: '취수구-수온', time: '2026-11-04 14:50', value: '' },
      { expl: '배수구-수온', time: '2026-11-04 14:50', value: '14.0' }
    ]
  };
  const v = L.buildPlantView('WS', plant, NOW);
  assert.equal(v.items.inTemp.num, null);
  assert.equal(v.diff, null);
});

test('온도차 반올림은 소수 첫째 자리, 부호 표기', () => {
  assert.equal(L.formatDiff(3.6), '+3.6');
  assert.equal(L.formatDiff(-0.4), '−0.4');
  assert.equal(L.formatDiff(0), '0.0');
  assert.equal(L.formatDiff(null), '—');
  const plant = {
    name: '월성',
    items: [
      { expl: '취수구-수온', time: '2026-11-04 14:50', value: '19.1' },
      { expl: '배수구-수온', time: '2026-11-04 14:50', value: '22.9' }
    ]
  };
  assert.equal(L.buildPlantView('WS', plant, NOW).diff, 3.8); // 부동소수점 오차(3.7999…) 없이 3.8
});

test('formatAge', () => {
  assert.equal(L.formatAge(0), '방금');
  assert.equal(L.formatAge(12), '12분 전');
  assert.equal(L.formatAge(60), '1시간 전');
  assert.equal(L.formatAge(135), '2시간 15분 전');
  assert.equal(L.formatAge(24 * 60), '1일 전');
  assert.equal(L.formatAge(120 * 24 * 60 + 3 * 60), '120일 3시간 전');
  assert.equal(L.formatAge(null), '');
});

test('formatTime: 오늘(KST)이면 시각만, 아니면 날짜 포함', () => {
  assert.equal(L.formatTime('2026-11-04 14:40', NOW), '14:40');
  assert.equal(L.formatTime('2026-07-07 10:19', NOW), '2026-07-07 10:19');
  assert.equal(L.formatTime(null, NOW), '-');
});

test('kstDate: UTC 15시 이후는 KST 다음 날', () => {
  assert.equal(L.kstDate(Date.UTC(2026, 10, 4, 14, 59)), '2026-11-04');
  assert.equal(L.kstDate(Date.UTC(2026, 10, 4, 15, 0)), '2026-11-05');
});

test('collectorStatus: 30분 초과 시 지연, 갱신 시각 없으면 알 수 없음', () => {
  const fresh = L.collectorStatus({ updated_at_utc: '2026-11-04T05:54:56Z' }, NOW);
  assert.equal(fresh.delayed, false);
  const old = L.collectorStatus({ updated_at_utc: '2026-11-04T05:00:00Z' }, NOW);
  assert.equal(old.delayed, true);
  assert.equal(L.collectorStatus({}, NOW).known, false);
});

/* ================= 추이 차트 순수 함수 ================= */

test('niceTicks: 깔끔한 눈금과 소수 자릿수', () => {
  const a = L.niceTicks(17.2, 23.4, 4);
  assert.ok(a.min <= 17.2 && a.max >= 23.4);
  assert.deepEqual(a.ticks.slice(0, 3), [a.ticks[0], a.ticks[0] + a.step, a.ticks[0] + 2 * a.step].map((v) => Number(v.toFixed(a.decimals))));
  assert.ok(a.ticks.length >= 3 && a.ticks.length <= 8, JSON.stringify(a.ticks));
  const b = L.niceTicks(3.2, 7.9, 4);
  assert.ok(b.min <= 3.2 && b.max >= 7.9);
  assert.ok(b.ticks.every((t) => Number.isFinite(t)));
});

test('niceTicks: 평평하거나 값이 하나면 ±0.5 로 확장', () => {
  const a = L.niceTicks(20, 20, 4);
  assert.ok(a.min < 20 && a.max > 20);
  assert.ok(a.ticks.length >= 2);
});

test('niceTicks: 부동소수점 오차 없이 정수·소수 눈금', () => {
  assert.deepEqual(L.niceTicks(0, 10, 5).ticks, [0, 2, 4, 6, 8, 10]);
  const t = L.niceTicks(0.1, 0.5, 4);
  assert.ok(t.ticks.every((v) => v === Number(v.toFixed(t.decimals))), JSON.stringify(t.ticks));
});

test('splitSegments: 간격이 gap 을 넘으면 선을 끊는다 (정확히 gap 은 잇는다)', () => {
  const pts = [[0, 1], [10, 2], [70, 3], [140, 4], [150, 5]];
  const segs = L.splitSegments(pts, 60);
  assert.deepEqual(segs.map((s) => s.length), [3, 2]); // 10→70 은 60 이므로 이음, 70→140 은 70 이라 끊음
  assert.deepEqual(L.splitSegments([], 60), []);
  assert.equal(L.splitSegments([[0, 1]], 60).length, 1);
});

test('nearestIndex: 가장 가까운 점, 경계와 빈 배열', () => {
  const pts = [[0, 1], [10, 2], [30, 3]];
  assert.equal(L.nearestIndex(pts, -5), 0);
  assert.equal(L.nearestIndex(pts, 4), 0);
  assert.equal(L.nearestIndex(pts, 6), 1);
  assert.equal(L.nearestIndex(pts, 21), 2);
  assert.equal(L.nearestIndex(pts, 999), 2);
  assert.equal(L.nearestIndex([], 5), -1);
});

test('diffSeries: 허용 오차 안의 짝만 (배수−취수), 소수 첫째 자리 반올림', () => {
  const inPts = [[0, 19.1], [10, 19.2], [100, 20.0]];
  const outPts = [[0, 22.9], [11, 23.0], [60, 25.0]];
  const d = L.diffSeries(inPts, outPts, 5);
  assert.deepEqual(d, [[0, 3.8], [11, 3.8]]); // 60 분 지점은 짝이 없어 제외, 22.9-19.1=3.8 (부동소수점 오차 없음)
});

test('xTicks: KST 정렬, 24시간은 시각·자정은 날짜 라벨, 일 단위는 MM/DD', () => {
  // 2026-11-04 15:00 KST = 06:00 UTC
  const end = Date.UTC(2026, 10, 4, 6, 0) / 60000;
  const x24 = L.xTicks(end - 1440, end, 270, 44);
  assert.ok(x24.step >= 60 && x24.step < 1440);
  assert.ok(x24.ticks.every((t) => (t.t + 540) % x24.step === 0), 'KST 기준 정렬');
  assert.ok(x24.ticks.length * 44 <= 270 + 44);
  const x7 = L.xTicks(end - 7 * 1440, end, 270, 44);
  assert.ok(x7.step >= 1440);
  assert.ok(x7.ticks.every((t) => /^\d\d\/\d\d$/.test(t.label)), JSON.stringify(x7.ticks));
  const x30 = L.xTicks(end - 30 * 1440, end, 270, 44);
  assert.ok(x30.ticks.length * 44 <= 270 + 44);
  // 자정 눈금은 날짜 라벨
  const mid = L.xTicks(end - 1440, end, 600, 44);
  assert.ok(mid.ticks.some((t) => /^\d\d\/\d\d$/.test(t.label)) || mid.step >= 1440);
});

test('formatKstFull', () => {
  assert.equal(L.formatKstFull(Date.UTC(2026, 10, 4, 6, 0) / 60000), '2026-11-04 15:00');
  assert.equal(L.formatKstFull(Date.UTC(2026, 10, 4, 15, 5) / 60000), '2026-11-05 00:05');
});

test('alignRows: 앵커 기준 행, 허용 오차 밖은 null, 최신순, 최대 행 수', () => {
  const anchor = [];
  for (let i = 0; i < 100; i++) anchor.push([i * 10, i]);
  const other = [[0, 100], [500, 200]];
  const rows = L.alignRows({ a: anchor, b: other }, 'a', 10, 5);
  assert.equal(rows.length, 10);
  assert.ok(rows[0].t > rows[rows.length - 1].t, '최신순');
  assert.equal(rows[0].t, 990); // 마지막 점 포함
  const first = rows[rows.length - 1];
  assert.equal(first.t, 0);
  assert.equal(first.vals.b, 100);
  assert.equal(rows[0].vals.b, null); // 990 근처엔 b 값 없음
  assert.equal(L.alignRows({ a: [] }, 'a', 10, 5).length, 0);
});

test('rangeByKey: 기본 24시간, 원본/평균 구분', () => {
  assert.equal(L.rangeByKey('7d').source, 'hourly');
  assert.equal(L.rangeByKey('24h').source, 'raw');
  assert.equal(L.rangeByKey('???').key, '24h');
  assert.equal(L.RANGES.length, 3);
});
