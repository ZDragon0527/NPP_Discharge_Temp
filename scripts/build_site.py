#!/usr/bin/env python3
"""GitHub Pages 배포용 사이트 폴더를 만든다 (표준 라이브러리만 사용).

  web/                    → <out>/                     (정적 화면)
  <data-dir>/latest.json  → <out>/data/latest.json     (본부별 최신값)
  <data-dir>/data/*.csv   → <out>/data/history.json    (추이 차트용 이력, 최근 30일)

history.json 구조 (시각은 모두 UTC 기준 epoch 분)
  {"generated_at_utc", "first_t", "raw_hours", "hourly_bucket_min",
   "plants": {"WS": {"inTemp": {"raw": [[t, v], ...], "hourly": [[t, v], ...]}, ...}}}
  - raw    : 최근 RAW_HOURS 시간의 원본 값 (24시간 보기)
  - hourly : 최근 HISTORY_DAYS 일의 1시간 평균 (7일·30일 보기). t 는 KST 정시(=UTC 정시) 시작 분
  - 오래된 값(stale)은 수집기가 CSV 에 저장하지 않으므로 이력에 들어가지 않는다.
CSV 원본 전체를 배포하지 않는 이유: 배포 크기와 시간을 줄이기 위해.
latest.json 이 없으면 빈 화면이 배포되지 않도록 실패한다.
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KST = dt.timezone(dt.timedelta(hours=9))
PLANTS = ("WS", "KR", "YK", "UJ")
ITEM_KEYS = {"취수구-수온": "inTemp", "배수구-수온": "outTemp", "취수구-염분": "inSal", "배수구-염분": "outSal"}
RAW_HOURS = 48
HISTORY_DAYS = 30
FUTURE_TOLERANCE_MIN = 120  # 시계 오차 허용. 이보다 미래 시각의 값은 버린다.


def to_minutes(time_kst):
    """'YYYY-MM-DD HH:MM'(KST) → epoch 분. 해석 불가면 None."""
    try:
        t = dt.datetime.strptime(time_kst, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except ValueError:
        return None
    return int(t.timestamp() // 60)


def load_points(data_dir, now_min, days=HISTORY_DAYS):
    """CSV → {(본부, 항목키): {t: 값}}. 같은 (본부, 항목, 시각)은 마지막 값 하나만 남긴다."""
    start_min = now_min - days * 1440
    # 파일명(YYYY-MM-DD)으로 오래된 파일은 읽지 않는다 (하루 여유)
    oldest_day = (dt.datetime.fromtimestamp(start_min * 60, KST) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    points = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "data", "*.csv"))):
        if os.path.basename(path)[:10] < oldest_day:
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key = ITEM_KEYS.get(row.get("expl", ""))
                plant = row.get("plant", "")
                t = to_minutes(row.get("time_kst", ""))
                if key is None or plant not in PLANTS or t is None:
                    continue
                if t < start_min or t > now_min + FUTURE_TOLERANCE_MIN:
                    continue
                try:
                    v = float(row.get("value", ""))
                except ValueError:
                    continue  # 빈 값·숫자 아님은 이력에 넣지 않는다
                if v != v or v in (float("inf"), float("-inf")):
                    continue
                points.setdefault((plant, key), {})[t] = v
    return points


def hourly_means(series):
    """[(t, v)] → 1시간 평균 [[버킷 시작 분, 평균]]. (UTC 정시 = KST 정시)"""
    buckets = {}
    for t, v in series:
        buckets.setdefault(t - t % 60, []).append(v)
    return [[b, round(sum(vs) / len(vs), 2)] for b, vs in sorted(buckets.items())]


def build_history(data_dir, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    now_min = int(now.timestamp() // 60)
    points = load_points(data_dir, now_min)
    raw_start = now_min - RAW_HOURS * 60
    plants = {}
    first_t = None
    for (plant, key), by_t in points.items():
        series = sorted(by_t.items())
        if series and (first_t is None or series[0][0] < first_t):
            first_t = series[0][0]
        plants.setdefault(plant, {})[key] = {
            "raw": [[t, v] for t, v in series if t >= raw_start],
            "hourly": hourly_means(series),
        }
    return {
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "first_t": first_t,
        "raw_hours": RAW_HOURS,
        "hourly_bucket_min": 60,
        "plants": plants,
    }


def build(data_dir, out, web_dir=None, now=None):
    web_dir = web_dir or os.path.join(ROOT, "web")
    src = os.path.join(data_dir, "latest.json")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"latest.json 이 없다: {src}")
    with open(src, encoding="utf-8") as f:
        json.load(f)  # 깨진 JSON 이면 여기서 실패
    history = build_history(data_dir, now)  # 출력 폴더를 지우기 전에 만들어 실패 시 기존 결과를 보존한다
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(web_dir, out)
    os.makedirs(os.path.join(out, "data"))
    shutil.copy(src, os.path.join(out, "data", "latest.json"))
    with open(os.path.join(out, "data", "history.json"), "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data-out", help="latest.json 과 data/*.csv 가 있는 디렉터리")
    ap.add_argument("--out", default="site", help="생성할 사이트 디렉터리")
    args = ap.parse_args(argv)
    try:
        out = build(args.data_dir, args.out)
    except (FileNotFoundError, ValueError) as e:
        print(f"오류: {e}")
        return 1
    size = os.path.getsize(os.path.join(out, "data", "history.json"))
    print(f"사이트 생성 완료: {out} (history.json {size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
