#!/usr/bin/env python3
"""온배수 현황 수집기 (표준 라이브러리만 사용).

4개 본부(genName=WS/KR/YK/UJ)의 현재값을 조회해
  <out>/data/YYYY-MM-DD.csv   일 단위 누적 이력 (중복 행·오래된 값은 저장하지 않음)
  <out>/latest.json           본부별 최신값과 상태 (화면용)
을 갱신한다. 일부 본부가 실패해도 성공한 본부는 저장하고, 호출 실패가 있으면 종료코드 1을 반환한다.

오래된 값(stale): 항목 시각이 현재보다 STALE_MINUTES 분을 넘게 지났거나 시각을 해석할 수 없는 항목.
  - CSV 이력에는 저장하지 않는다 (예: 갱신이 중단된 본부의 고정값 0 이 이력에 섞이지 않게).
  - latest.json 에는 stale=true 로 표시해 남긴다. 화면은 stale 항목의 값을 현재값처럼 보이면 안 된다.
  - 데이터 상태이므로 수집기 실패로 보지 않는다(종료코드 0). 로그에는 경고를 남긴다.

주의: 이 저장소는 공개될 예정이므로 로그도 공개된다.
인증키와 그 인코딩 변형은 ::add-mask:: 로 가리고, 키가 든 URL은 출력하지 않는다.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://apis.data.go.kr/B552041/inoutwater/getinoutwater"
PLANTS = {"WS": "월성", "KR": "고리", "YK": "한빛", "UJ": "한울"}
FIELDS = ["collected_at_utc", "plant", "time_kst", "name", "expl", "value"]
ITEM_TAGS = ("expl", "name", "time", "value")
TIMEOUT = 20
RETRIES = 3
STALE_MINUTES = 60
PROBE_MAX_STALE_DAYS = 7      # 이보다 오래 멈춘 본부(예: 고리 07-07)는 자동 진단하지 않는다
PROBE_REUSE_MINUTES = 60      # 같은 상태의 진단 결과는 이 시간 동안 재사용한다(호출 절약)
KST = dt.timezone(dt.timedelta(hours=9))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def mask_key(key):
    variants = {key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key),
                urllib.parse.unquote(key)}
    secrets = [v for v in variants if v]
    for v in secrets:
        print(f"::add-mask::{v}")
    return secrets


def scrub(text, secrets):
    for s in secrets:
        text = text.replace(s, "***")
    return text


def fetch_xml(key, plant, secrets, sleep=time.sleep, extra=None, headers=None, retries=None):
    """본부 하나를 조회해 XML 텍스트를 반환. 재시도 후에도 실패하면 RuntimeError.
    extra/headers/retries 는 자동 진단 전용(기본 파라미터 덮어쓰기·추가, 요청 헤더, 재시도 횟수)."""
    params = [("serviceKey", key), ("genName", plant), ("pageNo", "1"), ("numOfRows", "10")]
    for k, v in (extra or {}).items():
        params = [(pk, pv) for pk, pv in params if pk != k] + [(k, v)]
    url = BASE + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    req_headers = {"User-Agent": "npp-discharge-collector/0.1"}
    req_headers.update(headers or {})
    req = urllib.request.Request(url, headers=req_headers)
    attempts = retries or RETRIES
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            last = scrub(f"연결 실패: {getattr(e, 'reason', e)}", secrets)
        print(f"  [{plant}] 시도 {attempt}/{attempts} 실패: {last}")
        if attempt < attempts:
            sleep(5 * attempt)
    raise RuntimeError(last)


def parse(text):
    """XML → item dict 리스트. 정상 코드가 아니거나 item이 없으면 ValueError."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"XML 해석 실패: {e}") from e
    code = (root.findtext("header/resultCode") or "").strip()
    msg = (root.findtext("header/resultMsg") or "").strip()
    if code != "00":
        raise ValueError(f"resultCode={code or '-'} resultMsg={msg or '-'}")
    items = [{t: (it.findtext(t) or "").strip() for t in ITEM_TAGS}
             for it in root.findall("body/items/item")]
    if not items:
        raise ValueError("item 이 비어 있음")
    return items


def classify(items, now, stale_minutes):
    """각 항목에 age_minutes(경과 분, 해석 불가면 None)와 stale 여부를 붙인다."""
    out = []
    for it in items:
        try:
            t = dt.datetime.strptime(it["time"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
            age = int((now - t).total_seconds() // 60)
        except ValueError:
            age = None
        stale = age is None or age > stale_minutes
        out.append({**it, "age_minutes": age, "stale": stale})
    return out


def plant_status(items):
    stale = sum(1 for i in items if i["stale"])
    if stale == 0:
        return "ok"
    return "stale" if stale == len(items) else "partial_stale"


PROBE_VARIANTS = [
    ("B numOfRows=9", {"numOfRows": "9"}, None),
    ("C _=타임스탬프", "ts", None),                     # 호출 시점에 값 생성(캐시 키를 바꾸는 용도)
    ("D no-cache 헤더", {}, {"Cache-Control": "no-cache", "Pragma": "no-cache"}),
    ("E 기준 재호출", {}, None),                        # 시간에 따른 자연 갱신과 구분하기 위한 재호출
]


def newest_time(items):
    times = [i["time"] for i in items if i.get("time")]
    return max(times) if times else None


def probe_verdict(baseline, variants):
    """멈춘 본부가 원천 문제인지 게이트웨이 캐시인지 판정한다.
    - cache  : 호출 방식을 바꾼 변형이, 기준과 같은 주소 재호출(E) 중 더 최근 값보다도 최근 시각을 줌
    - updated: 같은 주소로 다시 불렀더니 새 값이 옴(자연 갱신. 캐시 TTL 만료와는 구분 불가)
    - source : 모든 변형이 같은 옛 시각 → 원천 쪽 갱신 정지
    - error  : 비교할 정상 응답 없음"""
    valid = {label: v for label, v in variants.items() if v}
    if not valid:
        return "error"
    repeat = variants.get("E 기준 재호출")
    ref = max(baseline, repeat) if repeat else baseline
    if any(v > ref for label, v in valid.items() if not label.startswith("E ")):
        return "cache"
    if repeat and repeat > baseline:
        return "updated"
    return "source"


def run_probe(key, code, secrets, baseline, probe_fetcher, checked_at, sleep=time.sleep):
    variants = {}
    for label, extra, headers in PROBE_VARIANTS:
        if extra == "ts":
            extra = {"_": str(int(time.time() * 1000))}
        try:
            variants[label] = newest_time(parse(probe_fetcher(key, code, secrets, extra, headers)))
        except (RuntimeError, ValueError):
            variants[label] = None
        sleep(1)
    return {"checked_at_utc": checked_at, "baseline": baseline, "variants": variants,
            "verdict": probe_verdict(baseline, variants)}


def probe_reusable(prior, baseline, now):
    """직전 진단이 같은 상태(같은 최신 시각)이고 PROBE_REUSE_MINUTES 안이면 재사용한다."""
    if not prior or prior.get("baseline") != baseline:
        return False
    try:
        at = dt.datetime.strptime(prior["checked_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (KeyError, ValueError):
        return False
    return (now - at).total_seconds() < PROBE_REUSE_MINUTES * 60


def load_latest(out):
    path = os.path.join(out, "latest.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"plants": {}}


PROBE_TEXT = {
    "source": "원천 쪽 갱신 정지(호출 방식을 바꿔도 같은 시각)",
    "cache": "캐시 의심(호출 방식을 바꾸면 더 최근 시각이 나옴)",
    "updated": "시험 도중 새 값 도착(자연 갱신)",
    "error": "판정 불가(정상 응답 부족)",
}


def day_of(item, fallback):
    return item["time"][:10] if DATE_RE.match(item["time"]) else fallback


def load_keys(path):
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {(r["plant"], r["name"], r["time_kst"]) for r in csv.DictReader(f)}


def append_rows(out, plant, items, collected_utc, kst_today):
    """신규 행만 일 단위 CSV에 추가하고 추가된 행 수를 반환."""
    data_dir = os.path.join(out, "data")
    added = 0
    by_day = {}
    for it in items:
        by_day.setdefault(day_of(it, kst_today), []).append(it)
    for day, day_items in by_day.items():
        path = os.path.join(data_dir, f"{day}.csv")
        existing = load_keys(path)
        new = os.path.exists(path)
        rows = [it for it in day_items if (plant, it["name"], it["time"]) not in existing]
        if not rows:
            continue
        os.makedirs(data_dir, exist_ok=True)
        with open(path, "a" if new else "w", newline="", encoding="utf-8" if new else "utf-8-sig") as f:
            w = csv.writer(f)
            if not new:
                w.writerow(FIELDS)
            for it in rows:
                w.writerow([collected_utc, plant, it["time"], it["name"], it["expl"], it["value"]])
        added += len(rows)
    return added


def update_latest(out, results, errors, collected_utc, stale_minutes=STALE_MINUTES, probes=None):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "latest.json")
    latest = {"plants": {}}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                latest = json.load(f)
        except (OSError, ValueError):
            latest = {"plants": {}}
    latest["updated_at_utc"] = collected_utc
    latest["stale_after_minutes"] = stale_minutes
    plants = latest.setdefault("plants", {})
    for code, items in results.items():
        plants[code] = {"name": PLANTS[code], "fetched_at_utc": collected_utc, "error": None,
                        "status": plant_status(items), "items": items}
        if probes and code in probes:
            plants[code]["probe"] = probes[code]      # 멈춘 본부의 자동 진단 결과(화면은 사용하지 않음)
    for code, err in errors.items():
        entry = plants.setdefault(code, {"name": PLANTS[code], "items": []})
        # 이전에 받은 값(items)은 보존하되, 호출 실패 상태임을 표시한다.
        entry["error"] = err
        entry["status"] = "error"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def run(key, out, fetcher=fetch_xml, sleep=time.sleep, now=None, stale_minutes=STALE_MINUTES, probe_fetcher=None):
    """수집 1회 실행. (신규 행 수, 호출 실패 본부 dict) 반환.
    probe_fetcher 가 있으면, 모든 항목이 멈춘 본부(최근 PROBE_MAX_STALE_DAYS 일 이내)를 호출 방식을 바꿔 다시 조회해
    원천 문제인지 캐시인지 판정하고 latest.json 의 probe 에 남긴다(진단 실패는 수집 실패로 보지 않는다)."""
    secrets = mask_key(key)
    now = now or dt.datetime.now(dt.timezone.utc)
    collected_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    kst_today = now.astimezone(KST).strftime("%Y-%m-%d")
    results, errors, total_new, probes = {}, {}, 0, {}
    prior_plants = load_latest(out).get("plants", {})
    for code, name in PLANTS.items():
        try:
            items = classify(parse(fetcher(key, code, secrets)), now, stale_minutes)
        except (RuntimeError, ValueError) as e:
            errors[code] = scrub(str(e), secrets)
            print(f"[{name}({code})] 호출 실패: {errors[code]}")
        else:
            fresh = [i for i in items if not i["stale"]]
            added = append_rows(out, code, fresh, collected_utc, kst_today)
            results[code] = items
            total_new += added
            status = plant_status(items)
            times = sorted({i["time"] for i in items})
            print(f"[{name}({code})] 상태={status}, item {len(items)}개, 시각 {', '.join(times)}, 신규 {added}행")
            if status != "ok":
                print(f"::warning::{name}({code}) 수신 지연/중단: 항목 시각이 {stale_minutes}분 넘게 지났거나 해석 불가 "
                      f"(최신 시각 {times[-1]})")
            for i in items:
                mark = " [오래됨]" if i["stale"] else ""
                print(f"    {i['name']:<12} {i['expl']:<12} {i['time']}  값={i['value'] or '(빈 값)'}{mark}")
            ages = [i["age_minutes"] for i in items if i["age_minutes"] is not None]
            if probe_fetcher is not None and status == "stale" and ages and min(ages) <= PROBE_MAX_STALE_DAYS * 1440:
                baseline = newest_time(items)
                prior = (prior_plants.get(code) or {}).get("probe")
                if probe_reusable(prior, baseline, now):
                    probes[code] = prior
                    print(f"  [진단] {name}({code}): 직전 진단 재사용 - {PROBE_TEXT.get(prior.get('verdict'), '?')}")
                else:
                    probes[code] = run_probe(key, code, secrets, baseline, probe_fetcher, collected_utc, sleep)
                    pv = probes[code]
                    line = f"  [진단] {name}({code}): {PROBE_TEXT[pv['verdict']]} | 기준 {baseline} | " + \
                           ", ".join(f"{k}={v or '실패'}" for k, v in pv["variants"].items())
                    print(("::warning::" if pv["verdict"] == "cache" else "") + line)
        sleep(1)
    update_latest(out, results, errors, collected_utc, stale_minutes, probes)
    return total_new, errors


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data-out", help="결과 저장 디렉터리")
    ap.add_argument("--stale-minutes", type=int, default=STALE_MINUTES,
                    help="이 시간(분)보다 오래된 항목은 이력에 저장하지 않고 stale 로 표시")
    args = ap.parse_args(argv)
    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not key:
        print("오류: 환경변수 DATA_GO_KR_SERVICE_KEY 가 비어 있다.")
        return 1
    def probe_fetch(k, code, secrets, extra, headers):
        return fetch_xml(k, code, secrets, extra=extra, headers=headers, retries=1)   # 진단은 재시도 없이 1회

    total_new, errors = run(key, args.out, stale_minutes=args.stale_minutes, probe_fetcher=probe_fetch)
    print(f"완료: 신규 {total_new}행, 호출 실패 본부 {len(errors)}곳")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
