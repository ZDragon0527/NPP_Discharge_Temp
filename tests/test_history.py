import csv
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)
import history as hist  # noqa: E402
import synthetic_history  # noqa: E402

NOW = dt.datetime(2026, 11, 4, 6, 0, tzinfo=dt.timezone.utc)  # 15:00 KST
FIELDS = ["collected_at_utc", "plant", "time_kst", "name", "expl", "value"]


def write_csv(data_dir, day, rows):
    os.makedirs(os.path.join(data_dir, "data"), exist_ok=True)
    with open(os.path.join(data_dir, "data", f"{day}.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for plant, expl, t, v in rows:
            w.writerow(["x", plant, t, "tag", expl, v])


def minutes(s):
    return hist.to_minutes(s)


class HistoryTest(unittest.TestCase):
    def test_empty_when_no_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = hist.build_history(tmp, NOW)
            self.assertEqual(h["plants"], {})
            self.assertIsNone(h["first_t"])

    def test_basic_series_and_first_t(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_csv(tmp, "2026-11-04", [
                ("WS", "취수구-수온", "2026-11-04 14:40", "19.3"),
                ("WS", "취수구-수온", "2026-11-04 14:50", "19.2"),
                ("WS", "배수구-수온", "2026-11-04 14:50", "22.9"),
            ])
            h = hist.build_history(tmp, NOW)
            raw = h["plants"]["WS"]["inTemp"]["raw"]
            self.assertEqual(raw, [[minutes("2026-11-04 14:40"), 19.3], [minutes("2026-11-04 14:50"), 19.2]])
            self.assertEqual(h["first_t"], minutes("2026-11-04 14:40"))
            self.assertNotIn("KR", h["plants"])

    def test_duplicates_ignored_and_bad_rows_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_csv(tmp, "2026-11-04", [
                ("WS", "취수구-수온", "2026-11-04 14:40", "19.3"),
                ("WS", "취수구-수온", "2026-11-04 14:40", "19.3"),   # 중복
                ("WS", "취수구-수온", "2026-11-04 14:45", ""),        # 빈 값
                ("WS", "취수구-수온", "2026-11-04 14:46", "abc"),     # 숫자 아님
                ("WS", "취수구-수온", "bad time", "1.0"),             # 시각 해석 불가
                ("WS", "알 수 없는 항목", "2026-11-04 14:40", "1.0"),  # 모르는 항목
                ("XX", "취수구-수온", "2026-11-04 14:40", "1.0"),     # 모르는 본부
                ("WS", "취수구-수온", "2026-11-05 14:40", "9.9"),     # 먼 미래
            ])
            h = hist.build_history(tmp, NOW)
            self.assertEqual(h["plants"]["WS"]["inTemp"]["raw"], [[minutes("2026-11-04 14:40"), 19.3]])
            self.assertEqual(list(h["plants"]), ["WS"])

    def test_raw_window_is_48h_and_hourly_covers_30_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_csv(tmp, "2026-10-20", [("WS", "취수구-수온", "2026-10-20 12:00", "10.0")])
            write_csv(tmp, "2026-11-03", [("WS", "취수구-수온", "2026-11-03 10:00", "11.0")])  # 29시간 전
            write_csv(tmp, "2026-11-01", [("WS", "취수구-수온", "2026-11-01 10:00", "12.0")])  # 3일 전
            write_csv(tmp, "2026-09-01", [("WS", "취수구-수온", "2026-09-01 10:00", "13.0")])  # 30일 초과
            h = hist.build_history(tmp, NOW)
            s = h["plants"]["WS"]["inTemp"]
            self.assertEqual([v for _, v in s["raw"]], [11.0])
            self.assertEqual([v for _, v in s["hourly"]], [10.0, 12.0, 11.0])
            self.assertNotIn(13.0, [v for _, v in s["hourly"]])

    def test_hourly_mean_and_bucket_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_csv(tmp, "2026-11-04", [
                ("WS", "취수구-수온", "2026-11-04 14:00", "19.0"),
                ("WS", "취수구-수온", "2026-11-04 14:30", "20.0"),
                ("WS", "취수구-수온", "2026-11-04 14:50", "21.0"),
                ("WS", "취수구-수온", "2026-11-04 13:50", "18.0"),
            ])
            hourly = hist.build_history(tmp, NOW)["plants"]["WS"]["inTemp"]["hourly"]
            self.assertEqual(hourly, [[minutes("2026-11-04 13:00"), 18.0], [minutes("2026-11-04 14:00"), 20.0]])
            self.assertEqual(hourly[0][0] % 60, 0)  # 정시 시작

    def test_synthetic_history_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            synthetic_history.generate(tmp, NOW, days=30)
            h = hist.build_history(tmp, NOW)
            self.assertEqual(sorted(h["plants"]), ["UJ", "WS", "YK"])  # 고리 없음
            ws = h["plants"]["WS"]["inTemp"]
            self.assertGreater(len(ws["raw"]), 200)
            self.assertLess(len(ws["raw"]), 300)  # 48시간·10분 간격 이하
            self.assertGreater(len(ws["hourly"]), 600)
            # 월성 3일 전 7시간 공백: 시간 평균에서 연속 버킷이 3시간 넘게 비어 있다
            ts = [t for t, _ in ws["hourly"]]
            self.assertTrue(any(b - a > 180 for a, b in zip(ts, ts[1:])))
            # 한빛은 공백 없음
            ts = [t for t, _ in h["plants"]["YK"]["inTemp"]["hourly"]]
            self.assertFalse(any(b - a > 120 for a, b in zip(ts, ts[1:])))

    def test_write_history_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_csv(tmp, "2026-11-04", [("WS", "취수구-수온", "2026-11-04 14:40", "19.3")])
            out, _ = hist.write_history(tmp, now=NOW)
            self.assertEqual(out, os.path.join(tmp, "history.json"))
            self.assertFalse(os.path.exists(out + ".tmp"))
            with open(out, encoding="utf-8") as f:
                h = json.load(f)
            self.assertEqual(h["plants"]["WS"]["inTemp"]["raw"][0][1], 19.3)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "data", "2026-11-04.csv")))  # CSV 는 그대로

    def test_prune_old_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            for day in ("2026-06-01", "2026-07-10", "2026-11-04"):
                write_csv(tmp, day, [("WS", "취수구-수온", day + " 10:00", "19")])
            removed = hist.prune_old_csv(tmp, 120, NOW)   # 기준일 2026-07-08
            self.assertEqual(removed, ["2026-06-01.csv"])
            self.assertEqual(sorted(os.listdir(os.path.join(tmp, "data"))), ["2026-07-10.csv", "2026-11-04.csv"])


if __name__ == "__main__":
    unittest.main()
