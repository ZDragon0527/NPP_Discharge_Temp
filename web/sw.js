/* 서비스 워커: 설치형 웹앱(PWA)과 오프라인 지원.
 *
 * 전략: 같은 출처의 GET 요청은 모두 "네트워크 우선, 실패/지연 시 저장본".
 *  - 값(latest.json, history.json)과 화면 코드가 항상 최신으로 받아지고(오래된 값을 최신처럼 보이는 일 방지),
 *    네트워크가 없을 때만 마지막으로 저장된 값을 보여준다. 저장본의 값이 오래되었는지는 화면이 현재 시각으로 다시 판단한다.
 *  - 저장 키에서 쿼리(?t=…)를 뺀다. 화면이 캐시 무효화용으로 붙이는 값 때문에 저장본이 무한히 늘지 않게 한다.
 *  - github.io 는 같은 사용자의 모든 사이트가 출처(origin)를 공유하므로, 정리할 때는 이 앱의 접두어(npp-discharge-)로
 *    시작하는 캐시만 지운다. 다른 사이트의 캐시를 건드리지 않는다.
 */
'use strict';

var CACHE = 'npp-discharge-v1';
var CACHE_PREFIX = 'npp-discharge-';
var NETWORK_TIMEOUT_MS = 4000;   // 저장본이 있을 때, 이 시간 안에 응답이 없으면 저장본을 보여준다
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

function fetchWithTimeout(request, ms) {
  var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, ms) : null;
  return fetch(request, ctrl ? { signal: ctrl.signal } : undefined).then(
    function (res) { if (timer) clearTimeout(timer); return res; },
    function (err) { if (timer) clearTimeout(timer); throw err; }
  );
}

function networkFirst(request) {
  var key = cacheKey(request);
  return caches.open(CACHE).then(function (cache) {
    return cache.match(key).then(function (cached) {
      // 저장본이 있으면 시간 제한을 두고, 없으면 네트워크를 끝까지 기다린다.
      var network = cached ? fetchWithTimeout(request, NETWORK_TIMEOUT_MS) : fetch(request);
      return network.then(function (res) {
        if (res && res.ok && res.type === 'basic') cache.put(key, res.clone());
        return res;
      }).catch(function (err) {
        if (cached) return cached;
        if (request.mode === 'navigate') {
          return cache.match(new Request(new URL('index.html', self.registration.scope).href)).then(function (shell) {
            if (shell) return shell;
            throw err;
          });
        }
        throw err;
      });
    });
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;       // 외부 요청은 건드리지 않는다
  event.respondWith(networkFirst(request));
});
