"""테스트·화면 점검 전용 합성 이력 생성기. 실제 데이터가 아니다.

수집기가 만드는 것과 같은 형식의 CSV(data/YYYY-MM-DD.csv)를 임의 디렉터리에 만든다.
- 월성: 10분 갱신, 3일 전 7시간 수집 공백(선 끊김 확인용)
- 한빛·한울: 5분 갱신(수집은 10분 간격이라 매 두 번째 값만 저장됨)
- 고리: 이력 없음(수신 중단 본부 확인용)
저장소에 합성 데이터를 커밋하지 않기 위해 파일 대신 생성기로 둔다.
"""
import csv
import datetime as dt
import math
import os
import random

KST = dt.timezone(dt.timedelta(hours=9))
FIELDS = ["collected_at_utc", "plant", "time_kst", "name", "expl", "value"]
# 본부: (갱신 주기 분, 계측 태그 접두어, 취수 수온 기준, 배수 수온 기준 온도차)
PLANTS = {"WS": (10, "2200", 17.0, 3.4), "YK": (5, "2300", 16.0, 5.5), "UJ": (5, "2400", 18.0, 7.0)}


def generate(data_dir, now, days=30, seed=7):
    rng = random.Random(seed)
    os.makedirs(os.path.join(data_dir, "data"), exist_ok=True)
    rows_by_day = {}
    step = 10  # 수집 간격(분)
    n = days * 1440 // step
    for i in range(n + 1):
        collected = now - dt.timedelta(minutes=(n - i) * step)
        for plant, (cadence, prefix, base, diff0) in PLANTS.items():
            if plant == "WS" and 3 * 1440 + 420 > (n - i) * step >= 3 * 1440:
                continue  # 3일 전 7시간 수집 공백
            local = collected.astimezone(KST)
            t = local.replace(minute=local.minute - local.minute % cadence, second=0, microsecond=0)
            days_f = (collected - now).total_seconds() / 86400
            hour = local.hour + local.minute / 60
            t_in = base + 2.5 * math.sin(2 * math.pi * days_f / 14) + 0.7 * math.sin(2 * math.pi * hour / 24) + rng.gauss(0, 0.08)
            dd = diff0 + 1.0 * math.sin(2 * math.pi * hour / 24 + 1) + rng.gauss(0, 0.15)
            s_in = 30 + 1.5 * math.sin(2 * math.pi * days_f / 9) + rng.gauss(0, 0.1)
            s_out = s_in + 1.8 + rng.gauss(0, 0.1)
            for name_suffix, expl, v in (("RM001", "취수구-수온", t_in), ("RM002", "취수구-염분", s_in),
                                         ("RM005", "배수구-수온", t_in + dd), ("RM006", "배수구-염분", s_out)):
                day = t.strftime("%Y-%m-%d")
                rows_by_day.setdefault(day, {})[(plant, expl, t.strftime("%Y-%m-%d %H:%M"))] = [
                    collected.strftime("%Y-%m-%dT%H:%M:%SZ"), plant, t.strftime("%Y-%m-%d %H:%M"),
                    f"{prefix}-{name_suffix}", expl, f"{v:.1f}"]
    for day, rows in rows_by_day.items():
        with open(os.path.join(data_dir, "data", f"{day}.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            w.writerows(rows.values())
    return data_dir
