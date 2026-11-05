#!/usr/bin/env python3
"""배포 반영 확인 (표준 라이브러리만 사용).

배포 직후 공개 사이트의 data/latest.json 을 다시 읽어, 방금 배포한 값(--expected)보다 얼마나 뒤처졌는지 본다.
뒤처진 정도가 --max-lag-min 을 넘으면 실패(종료코드 1)로 끝내 워크플로를 실패로 표시한다(알림 메일).

배경: 2026-11-05 GitHub Pages 가 14:40 UTC 배포본에 멈춰 이후 약 8시간 동안 "배포 성공"이 계속 보고됐지만
공개 사이트는 갱신되지 않았다. 배포 단계의 성공만으로는 이 상황을 알 수 없다.

- GitHub Pages 의 CDN 은 최대 10분(max-age=600) 캐시하므로 정확히 같을 때만 통과시키면 정상일 때도 오경보가 난다.
  그래서 기본 허용 지연을 12분(캐시 10분 + 여유)으로 둔다.
- 통과 조건을 만족할 때까지 --interval 초마다 다시 읽고, --timeout 초 안에 만족하지 않으면 실패한다.
- 로그에는 공개 사이트와 방금 배포한 값의 본부별 최신 측정 시각도 남긴다(API 가 옛 값을 주는 경우와 구분하기 위해).
"""
import argparse
import datetime as dt
import json
import random
import sys
import time
import urllib.error
import urllib.request

LATEST_PATH = "data/latest.json"


def parse_utc(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def fetch_live(base_url, timeout=20):
    """공개 사이트의 latest.json 을 받아 dict 로 반환. 실패하면 (None, 사유)."""
    url = base_url.rstrip("/") + "/" + LATEST_PATH + f"?cb={int(time.time())}{random.randint(0, 9999)}"
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "npp-discharge-verify-live/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"연결 실패: {getattr(e, 'reason', e)}"
    except ValueError as e:
        return None, f"JSON 해석 실패: {e}"


def newest_times(doc):
    """본부별 가장 최근 항목 시각(KST 문자열)."""
    out = {}
    for code, plant in (doc.get("plants") or {}).items():
        times = sorted(i.get("time", "") for i in plant.get("items", []) if i.get("time"))
        out[code] = times[-1] if times else "-"
    return out


def lag_minutes(live_doc, expected_doc):
    """방금 배포한 값보다 공개 사이트가 몇 분 뒤처졌는지. 앞서 있거나 같으면 0."""
    live = parse_utc(live_doc["updated_at_utc"])
    exp = parse_utc(expected_doc["updated_at_utc"])
    return max(0, int((exp - live).total_seconds() // 60))


def verify(base_url, expected_doc, max_lag_min=12, timeout=150, interval=15,
           fetch=fetch_live, sleep=time.sleep, clock=time.monotonic, log=print):
    """통과하면 True. 시간 안에 통과 조건을 만족하지 못하면 False."""
    deadline = clock() + timeout
    attempt = 0
    last = "응답 없음"
    while True:
        attempt += 1
        live_doc, err = fetch(base_url)
        if live_doc is None:
            last = err
            log(f"[{attempt}] 공개 사이트 읽기 실패: {err}")
        else:
            try:
                lag = lag_minutes(live_doc, expected_doc)
            except (KeyError, ValueError) as e:
                last = f"updated_at_utc 해석 실패: {e}"
                log(f"[{attempt}] {last}")
            else:
                last = f"공개 사이트 {live_doc['updated_at_utc']} / 배포본 {expected_doc['updated_at_utc']} (뒤처짐 {lag}분)"
                log(f"[{attempt}] {last}")
                if lag <= max_lag_min:
                    log(f"통과: 공개 사이트가 배포본보다 {lag}분 뒤처짐(허용 {max_lag_min}분 이하).")
                    return True
        if clock() >= deadline:
            break
        sleep(interval)
    log(f"::error::배포는 성공으로 보고됐지만 공개 사이트에 반영되지 않았습니다. {last}")
    if live_doc is not None:
        log("공개 사이트 본부별 최신 측정 시각: " + json.dumps(newest_times(live_doc), ensure_ascii=False))
    log("배포본 본부별 최신 측정 시각:      " + json.dumps(newest_times(expected_doc), ensure_ascii=False))
    return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="공개 사이트 주소(예: https://<사용자>.github.io/<저장소>/)")
    ap.add_argument("--expected", required=True, help="방금 배포한 latest.json 경로")
    ap.add_argument("--max-lag-min", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=150)
    ap.add_argument("--interval", type=int, default=15)
    args = ap.parse_args(argv)
    try:
        with open(args.expected, encoding="utf-8") as f:
            expected = json.load(f)
        parse_utc(expected["updated_at_utc"])
    except (OSError, ValueError, KeyError) as e:
        print(f"오류: 배포본 latest.json 을 읽을 수 없다: {e}")
        return 1
    ok = verify(args.url, expected, args.max_lag_min, args.timeout, args.interval)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
