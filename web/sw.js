/* 서비스 워커: 설치형 웹앱(PWA)과 오프라인 지원.
 *
 * 전략: 화면 파일(같은 출처)과 측정 데이터(raw.githubusercontent.com)는 모두 "네트워크 우선, 실패/지연 시 저장본".
 *  - 값과 화면 코드가 항상 최신으로 받아지고(오래된 값을 최신처럼 보이는 일 방지),
 *    네트워크가 없거나 느릴 때만 마지막으로 저장된 값을 보여준다.
 *    저장된 값이 오래되었는지는 화면이 현재 시각으로 다시 판단한다.
 *  - 저장본이 있을 때 응답이 NETWORK_TIMEOUT_MS 안에 오지 않으면 저장본을 먼저 보여주되,
 *    요청은 중단하지 않고 끝까지 받아 저장본을 갱신한다(다음 접속에서는 최신이 나온다).
 *  - 저장본을 보여줄 때는 응답에 X-NPP-From-Cache: 1 헤더를 붙여 화면이 "이 기기에 저장된 값"임을 안내하게 한다.
 *  - 저장 키에서 쿼리(?…)를 뺀다. 캐시 무효화용 값 때문에 저장본이 무한히 늘지 않게 한다.
 *  - github.io 는 같은 사용자의 모든 사이트가 출처(origin)를 공유하므로, 정리할 때는 이 앱의 접두어(npp-discharge-)로
 *    시작하는 캐시만 지운다. 다른 사이트의 캐시를 건드리지 않는다.
 */
'use strict';

var CACHE = 'npp-discharge-v2';
var CACHE_PREFIX = 'npp-discharge-';
var NETWORK_TIMEOUT_MS = 4000;
var DEFAULT_DATA_BASE = 'https://raw.githubusercontent.com/ZDragon0527/NPP_Discharge_Temp/data/';
// 화면(app.js)이 등록할 때 ?data=<측정 데이터 주소> 를 넘겨 서비스 워커와 화면이 같은 주소를 쓰게 한다.
var DATA_BASE = new URL(self.location.href).searchParams.get('data') || DEFAULT_DATA_BASE;
var SHELL = [
  './',
  'index.html',
  'style.css',
  'logic.js',
  'chart.js',
  'trend.js',
  'app.js',
  'manifest.webmanifest',
  'icons/icon.svg',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/apple-touch-icon.png'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE)
      .then(function (cache) { return cache.addAll(SHELL.map(function (u) { return new Request(u, { cache: 'reload' }); })); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys
          .filter(function (k) { return k.indexOf(CACHE_PREFIX) === 0 && k !== CACHE; })
          .map(function (k) { return caches.delete(k); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

function cacheKey(request) {
  var url = new URL(request.url);
  return new Request(url.origin + url.pathname);
}

/** 저장본을 새 Response 로 감싸 X-NPP-From-Cache 헤더를 붙인다. */
function markCached(response) {
  var headers = new Headers(response.headers);
  headers.set('X-NPP-From-Cache', '1');
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers: headers });
}

function networkFirst(event, request) {
  var key = cacheKey(request);
  return caches.open(CACHE).then(function (cache) {
    return cache.match(key).then(function (cached) {
      var network = fetch(request).then(function (res) {
        if (res && res.ok && (res.type === 'basic' || res.type === 'cors')) cache.put(key, res.clone());
        return res;
      });
      var outcome = network.then(function (res) { return { res: res }; }, function (err) { return { err: err }; });
      event.waitUntil(outcome);   // 응답을 돌려준 뒤에도 저장본 갱신이 끝날 때까지 서비스 워커를 유지한다.

      function fallback(err) {
        if (cached) return markCached(cached);
        if (request.mode === 'navigate') {
          return cache.match(new Request(new URL('index.html', self.registration.scope).href)).then(function (shell) {
            if (shell) return shell;
            throw err;
          });
        }
        throw err;
      }

      if (!cached) {
        return outcome.then(function (o) { return o.res ? o.res : fallback(o.err); });
      }
      var timeout = new Promise(function (resolve) { setTimeout(function () { resolve({ timeout: true }); }, NETWORK_TIMEOUT_MS); });
      return Promise.race([outcome, timeout]).then(function (o) {
        if (o.timeout) return fallback(new Error('timeout'));
        return o.res ? o.res : fallback(o.err);
      });
    });
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') return;
  var url = new URL(request.url);
  var isData = url.href.indexOf(DATA_BASE) === 0;
  if (url.origin !== self.location.origin && !isData) return;   // 그 밖의 외부 요청은 가로채지 않는다
  event.respondWith(networkFirst(event, request));
});
