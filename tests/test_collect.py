import csv
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import collect  # noqa: E402

# 2026-11-04 검증 실행에서 받은 월성 응답 구조(값은 당시 응답 그대로)
WS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode>'
    "<resultMsg>NORMAL SERVICE.</resultMsg></header><body><items>"
    "<item><expl>취수구-수온</expl><name>2200-RM001</name><time>{t}</time><value>19.3</value></item>"
    "<item><expl>취수구-염분</expl><name>2200-RM002</name><time>{t}</time><value>29.3</value></item>"
    "<item><expl>배수구-수온</expl><name>2220-RM005</name><time>{t}</time><value>22.9</value></item>"
    "<item><expl>배수구-염분</expl><name>2220-RM006</name><time>{t}</time><value>{v}</value></item>"
    "</items><numOfRows>10</numOfRows><pageNo>1</pageNo><totalCount>4</totalCount></body></response>"
)
EMPTY_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode>'
    "<resultMsg>NORMAL SERVICE.</resultMsg></header><body><items/><totalCount>0</totalCount></body></response>"
)
ERR_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>30</resultCode>'
    "<resultMsg>SERVICE KEY IS NOT REGISTERED ERROR.</resultMsg></header></response>"
)
NOW = dt.datetime(2026, 11, 4, 5, 41, tzinfo=dt.timezone.utc)


def fetcher_factory(t="2026-11-04 14:40", v="31.4", broken=()):
    def fetcher(key, plant, secrets):
        if plant in broken:
            raise RuntimeError("HTTP 500")
        return WS_XML.format(t=t, v=v)
    return fetcher


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class CollectTest(unittest.TestCase):
    def run_once(self, out, **kw):
        fetcher = kw.pop("fetcher", fetcher_factory())
        return collect.run("TESTKEY+a/b==", out, fetcher=fetcher, sleep=lambda s: None, now=NOW)

    def test_parse_ok(self):
        items = collect.parse(WS_XML.format(t="2026-11-04 14:40", v="31.4"))
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0], {"expl": "취수구-수온", "name": "2200-RM001",
                                    "time": "2026-11-04 14:40", "value": "19.3"})

    def test_parse_rejects_empty_and_error_codes(self):
        with self.assertRaises(ValueError):
            collect.parse(EMPTY_XML)
        with self.assertRaises(ValueError):
            collect.parse(ERR_XML)
        with self.assertRaises(ValueError):
            collect.parse("<html>not xml")

    def test_first_run_writes_csv_and_latest(self):
        with tempfile.TemporaryDirectory() as out:
            new, errors = self.run_once(out)
            self.assertEqual((new, errors), (16, {}))  # 4개 본부 x 4개 항목
            rows = read_csv(os.path.join(out, "data", "2026-11-04.csv"))
            self.assertEqual(len(rows), 16)
            self.assertEqual(rows[0]["collected_at_utc"], "2026-11-04T05:41:00Z")
            self.assertEqual({r["plant"] for r in rows}, {"WS", "KR", "YK", "UJ"})
            with open(os.path.join(out, "latest.json"), encoding="utf-8") as f:
                latest = json.load(f)
            self.assertEqual(latest["plants"]["WS"]["name"], "월성")
            self.assertEqual(len(latest["plants"]["WS"]["items"]), 4)
            self.assertIsNone(latest["plants"]["WS"]["error"])

    def test_dedup_same_timestamp(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out)
            new, _ = self.run_once(out)
            self.assertEqual(new, 0)
            self.assertEqual(len(read_csv(os.path.join(out, "data", "2026-11-04.csv"))), 16)

    def test_new_timestamp_appends_without_second_header(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out)
            new, _ = self.run_once(out, fetcher=fetcher_factory(t="2026-11-04 14:50"))
            self.assertEqual(new, 16)
            path = os.path.join(out, "data", "2026-11-04.csv")
            self.assertEqual(len(read_csv(path)), 32)
            with open(path, encoding="utf-8-sig") as f:
                self.assertEqual(sum(1 for line in f if line.startswith("collected_at_utc")), 1)

    def test_day_rollover_goes_to_new_file(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out, fetcher=fetcher_factory(t="2026-11-05 00:00"))
            self.assertTrue(os.path.exists(os.path.join(out, "data", "2026-11-05.csv")))

    def test_failure_keeps_other_plants_and_old_values(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out)
            new, errors = self.run_once(out, fetcher=fetcher_factory(t="2026-11-04 14:50", broken=("KR",)))
            self.assertEqual(list(errors), ["KR"])
            self.assertEqual(new, 12)  # KR 제외 3개 본부 x 4
            with open(os.path.join(out, "latest.json"), encoding="utf-8") as f:
                latest = json.load(f)
            self.assertEqual(latest["plants"]["KR"]["error"], "HTTP 500")
            self.assertEqual(len(latest["plants"]["KR"]["items"]), 4)  # 이전 값 보존
            self.assertEqual(latest["plants"]["WS"]["items"][0]["time"], "2026-11-04 14:50")

    def test_stale_plant_is_flagged_and_not_stored(self):
        """고리 실사례: 4개월 전 시각 + 값 0 → 이력 미저장, latest 에는 stale 로 표시."""
        def fetcher(key, plant, secrets):
            t = "2026-07-07 10:19" if plant == "KR" else "2026-11-04 14:40"
            return WS_XML.format(t=t, v="0" if plant == "KR" else "31.4")
        with tempfile.TemporaryDirectory() as out:
            new, errors = self.run_once(out, fetcher=fetcher)
            self.assertEqual((new, errors), (12, {}))  # KR 4행 제외
            self.assertFalse(os.path.exists(os.path.join(out, "data", "2026-07-07.csv")))
            rows = read_csv(os.path.join(out, "data", "2026-11-04.csv"))
            self.assertNotIn("KR", {r["plant"] for r in rows})
            with open(os.path.join(out, "latest.json"), encoding="utf-8") as f:
                latest = json.load(f)
            self.assertEqual(latest["stale_after_minutes"], 60)
            self.assertEqual(latest["plants"]["KR"]["status"], "stale")
            self.assertTrue(all(i["stale"] for i in latest["plants"]["KR"]["items"]))
            self.assertEqual(latest["plants"]["WS"]["status"], "ok")
            self.assertFalse(any(i["stale"] for i in latest["plants"]["WS"]["items"]))

    def test_stale_boundary_is_60_minutes(self):
        now = dt.datetime(2026, 11, 4, 6, 0, tzinfo=dt.timezone.utc)  # 15:00 KST
        items = [{"expl": "e", "name": "n", "value": "1", "time": t}
                 for t in ("2026-11-04 14:00", "2026-11-04 13:59", "bad time")]
        out = collect.classify(items, now, 60)
        self.assertEqual([i["stale"] for i in out], [False, True, True])  # 60분은 정상, 61분·해석 불가는 stale
        self.assertEqual([i["age_minutes"] for i in out], [60, 61, None])

    def test_partial_stale_status(self):
        items = collect.classify(
            [{"expl": "a", "name": "1", "value": "1", "time": "2026-11-04 14:40"},
             {"expl": "b", "name": "2", "value": "1", "time": "2026-11-04 10:00"}], NOW, 60)
        self.assertEqual(collect.plant_status(items), "partial_stale")

    def test_call_failure_marks_error_status_and_keeps_items(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out)
            self.run_once(out, fetcher=fetcher_factory(broken=("KR",)))
            with open(os.path.join(out, "latest.json"), encoding="utf-8") as f:
                latest = json.load(f)
            self.assertEqual(latest["plants"]["KR"]["status"], "error")
            self.assertEqual(len(latest["plants"]["KR"]["items"]), 4)

    def test_blank_value_is_stored_as_is(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out, fetcher=fetcher_factory(v=""))
            rows = read_csv(os.path.join(out, "data", "2026-11-04.csv"))
            self.assertTrue(any(r["name"] == "2220-RM006" and r["value"] == "" for r in rows))


if __name__ == "__main__":
    unittest.main()
