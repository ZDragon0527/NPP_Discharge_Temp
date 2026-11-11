#!/usr/bin/env python3
"""data 브랜치에 올리기 전 안전 검사 (표준 라이브러리만 사용).

data 브랜치는 매번 커밋 1개로 덮어쓴다(force push). 그래서 한 번 잘못 올리면 이전 상태로 돌아가기 어렵다.
이 검사가 실패하면 게시를 중단한다.

  snapshot : 현재 data 디렉터리의 CSV 별 행 수를 JSON 으로 저장 (수집 전에 실행)
  verify   : 수집·이력 생성 후, 다음을 확인한다 (하나라도 어긋나면 종료코드 1)
             1) latest.json 이 올바른 JSON 이고 plants·updated_at_utc 가 있다
             2) history.json 이 올바른 JSON 이고 plants·generated_at_utc 가 있다
             3) 보존 기간 안의 CSV 가 사라지거나 행 수가 줄지 않았다 (이력은 늘기만 해야 한다)

사용:
  python3 scripts/check_data_dir.py snapshot --data-dir data-out --out prev-counts.json
  python3 scripts/check_data_dir.py verify --data-dir data-out --prev prev-counts.json --keep-days 120
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os
import sys

KST = dt.timezone(dt.timedelta(hours=9))


def count_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return sum(1 for _ in csv.reader(f)) - 1  # 머리글 제외


def csv_counts(data_dir):
    counts = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "data", "*.csv"))):
        counts[os.path.basename(path)] = max(0, count_rows(path))
    return counts


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def verify(data_dir, prev_counts, keep_days=0, now=None):
    """문제 목록(빈 목록이면 통과)을 반환."""
    problems = []
    now = now or dt.datetime.now(dt.timezone.utc)

    latest_path = os.path.join(data_dir, "latest.json")
    try:
        latest = load_json(latest_path)
        if not isinstance(latest.get("plants"), dict) or not latest["plants"]:
            problems.append("latest.json 에 plants 가 없다")
        if not latest.get("updated_at_utc"):
            problems.append("latest.json 에 updated_at_utc 가 없다")
    except (OSError, ValueError) as e:
        problems.append(f"latest.json 을 읽을 수 없다: {e}")

    history_path = os.path.join(data_dir, "history.json")
    try:
        history = load_json(history_path)
        if not isinstance(history.get("plants"), dict):
            problems.append("history.json 에 plants 가 없다")
        if not history.get("generated_at_utc"):
            problems.append("history.json 에 generated_at_utc 가 없다")
    except (OSError, ValueError) as e:
        problems.append(f"history.json 을 읽을 수 없다: {e}")

    cutoff = None
    if keep_days > 0:
        cutoff = (now.astimezone(KST) - dt.timedelta(days=keep_days)).strftime("%Y-%m-%d")
    new_counts = csv_counts(data_dir)
    for name, before in sorted(prev_counts.items()):
        if cutoff and name[:10] < cutoff:
            continue  # 보존 기간 밖의 파일은 정리 대상이므로 검사하지 않는다
        after = new_counts.get(name)
        if after is None:
            problems.append(f"CSV 가 사라졌다: {name} (이전 {before}행)")
        elif after < before:
            problems.append(f"CSV 행 수가 줄었다: {name} ({before}행 → {after}행)")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--data-dir", required=True)
    s.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--data-dir", required=True)
    v.add_argument("--prev", required=True)
    v.add_argument("--keep-days", type=int, default=0)
    args = ap.parse_args(argv)

    if args.cmd == "snapshot":
        counts = csv_counts(args.data_dir)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(counts, f, ensure_ascii=False)
        print(f"스냅샷: CSV {len(counts)}개, 총 {sum(counts.values()):,}행")
        return 0

    try:
        prev = load_json(args.prev)
    except (OSError, ValueError) as e:
        print(f"::error::이전 스냅샷을 읽을 수 없어 게시를 중단한다: {e}")
        return 1
    problems = verify(args.data_dir, prev, args.keep_days)
    now_counts = csv_counts(args.data_dir)
    if problems:
        for p in problems:
            print(f"::error::{p}")
        print("data 브랜치 게시를 중단한다(덮어쓰면 이전 상태로 되돌리기 어렵다).")
        return 1
    print(f"검사 통과: CSV {len(now_counts)}개, 총 {sum(now_counts.values()):,}행 (이전 {sum(prev.values()):,}행)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
