#!/usr/bin/env python3
"""수신 중단 원인 진단: API 가 옛 시각을 돌려줄 때 그것이 원천(KHNP) 문제인지 게이트웨이 캐시인지 가른다.

같은 본부에 대해 호출 주소·헤더를 달리한 변형을 보내 최신 항목 시각이 달라지는지 비교한다.
  A 기준          수집기와 완전히 같은 주소 (genName, pageNo=1, numOfRows=10)
  B numOfRows=9   주소의 값만 바꿈
  C _=타임스탬프   알 수 없는 파라미터를 추가(캐시 키를 바꾸는 용도)
  D no-cache      기준 주소 + Cache-Control: no-cache 헤더
  E 기준 재호출    A 를 마지막에 한 번 더(시간에 따른 변화 확인)
판정
  - 어떤 변형이 기준보다 더 최근 시각을 주면 → 게이트웨이/중간 캐시 의심(주소를 바꾸면 최신이 나옴)
  - 모든 변형이 같은 시각이면 → 원천 쪽에서 갱신이 멈춘 것(호출 방식과 무관)

주의: 이 저장소는 공개이므로 로그도 공개된다. 인증키와 그 변형은 ::add-mask:: 로 가리고,
키가 든 URL은 출력하지 않는다. 응답 본문은 출력하지 않고 시각·개수·헤더만 출력한다.
"""
import datetime as dt
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://apis.data.go.kr/B552041/inoutwater/getinoutwater"
PLANTS = {"WS": "월성", "KR": "고리", "YK": "한빛", "UJ": "한울"}
TIMEOUT = 20
KST = dt.timezone(dt.timedelta(hours=9))
HEADER_KEYS = ("date", "age", "cache-control", "expires", "last-modified", "etag", "via", "server", "vary")


def mask_key(key):
    variants = {key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key), urllib.parse.unquote(key)}
    secrets = [v for v in variants if v]
    for v in secrets:
        print(f"::add-mask::{v}")
    return secrets


def scrub(text, secrets):
    for s in secrets:
        text = text.replace(s, "***")
    return text


def fetch(key, secrets, code, extra=None, headers=None):
    """GET 한 번 → dict(status, code, items, newest, headers, error). 본문은 돌려주지 않는다."""
    params = [("serviceKey", key), ("genName", code), ("pageNo", "1"), ("numOfRows", "10")]
    for k, v in (extra or {}).items():
        params = [(pk, pv) for pk, pv in params if pk != k] + [(k, v)]
    url = BASE + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    h = {"User-Agent": "npp-discharge-probe/0.1"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        hdrs, status = {k.lower(): v for k, v in e.headers.items()}, e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"status": 0, "code": "-", "items": 0, "newest": "-", "headers": {},
                "error": scrub(f"연결 실패: {getattr(e, 'reason', e)}", secrets)}
    body = scrub(body, secrets)
    return {"status": status, "code": tag(body, "resultCode") or "-", "items": len(re.findall(r"<item[ >]", body)),
            "newest": newest_time(body), "headers": pick_headers(hdrs), "error": None}


def tag(body, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", body, re.S)
    return m.group(1).strip() if m else ""


def newest_time(body):
    times = re.findall(r"<time>(.*?)</time>", body, re.S)
    times = [t.strip() for t in times if t.strip()]
    return max(times) if times else "-"


def pick_headers(hdrs):
    """캐시 판단에 쓸 헤더만 추린다(이름에 cache 가 들어간 헤더 포함)."""
    return {k: v for k, v in hdrs.items() if k in HEADER_KEYS or "cache" in k}


VARIANTS = [
    ("A 기준", {}, None),
    ("B numOfRows=9", {"numOfRows": "9"}, None),
    ("C _=타임스탬프", None, None),   # 실행 시점에 값 생성
    ("D no-cache 헤더", {}, {"Cache-Control": "no-cache", "Pragma": "no-cache"}),
    ("E 기준 재호출", {}, None),
]


def probe_plant(key, secrets, code, fetch_fn=fetch, sleep=time.sleep):
    results = []
    for label, extra, headers in VARIANTS:
        if extra is None:
            extra = {"_": str(int(time.time() * 1000))}
        results.append((label, fetch_fn(key, secrets, code, extra, headers)))
        sleep(1)
    return results


def verdict(results):
    """(판정 코드, 설명). 코드: cache | source | error."""
    ok = [(l, r) for l, r in results if r["status"] == 200 and r["code"] == "00" and r["newest"] != "-"]
    if len(ok) < 2:
        return "error", "비교할 정상 응답이 부족함"
    base = dict(ok)[ "A 기준" ] if "A 기준" in dict(ok) else ok[0][1]
    fresher = [(l, r["newest"]) for l, r in ok if r["newest"] > base["newest"]]
    if fresher:
        return "cache", "기준보다 최근 시각을 준 변형: " + ", ".join(f"{l}={t}" for l, t in fresher)
    return "source", f"모든 변형이 같은 최신 시각({base['newest']})"


def main():
    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not key:
        print("오류: 환경변수 DATA_GO_KR_SERVICE_KEY 가 비어 있다.")
        return 1
    secrets = mask_key(key)
    now = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    print(f"진단 시각 {now} KST (이보다 60분 넘게 오래된 최신 시각이면 수신 중단 상태)")
    rows = []
    for code, name in PLANTS.items():
        print(f"\n=== {name}({code}) ===")
        results = probe_plant(key, secrets, code)
        for label, r in results:
            err = f" 오류={r['error']}" if r["error"] else ""
            print(f"  {label:<16} HTTP={r['status']} resultCode={r['code']} item={r['items']} 최신시각={r['newest']}{err}")
        base_headers = results[0][1]["headers"]
        if base_headers:
            print("  응답 헤더(기준):", "; ".join(f"{k}={v}" for k, v in base_headers.items()))
        kind, text = verdict(results)
        label = {"cache": "캐시 의심", "source": "원천 쪽(변형과 무관)", "error": "판정 불가"}[kind]
        print(f"  판정: {label} - {text}")
        rows.append((name, code, results[0][1]["newest"], label, text))
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        lines = ["## 수신 중단 진단 결과", "", f"진단 시각 {now} KST", "",
                 "| 본부 | 기준 최신 시각 | 판정 | 상세 |", "|---|---|---|---|"]
        lines += [f"| {n}({c}) | {t} | {l} | {d} |" for n, c, t, l, d in rows]
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
