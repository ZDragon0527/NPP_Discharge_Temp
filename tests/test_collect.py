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


class ProbeTest(unittest.TestCase):
    """멈춘 본부의 자동 진단(원천 문제인지 캐시인지)."""
    FRESH = "2026-11-04 14:40"
    STALE = "2026-11-03 13:00"      # NOW(11-04 14:41 KST) 기준 약 26시간 전 → 모든 항목 stale, 7일 이내
    TOO_OLD = "2026-07-07 10:19"    # 7일 초과

    def fetcher(self, stale_plants=(), stale_time=None):
        stale_time = stale_time or self.STALE

        def f(key, plant, secrets):
            return WS_XML.format(t=stale_time if plant in stale_plants else self.FRESH, v="1.0")
        return f

    def run_with_probe(self, out, probe, now=NOW, fetcher=None):
        return collect.run("TESTKEY+a/b==", out, fetcher=fetcher or self.fetcher(("UJ",)), sleep=lambda s: None,
                           now=now, probe_fetcher=probe)

    def latest(self, out):
        with open(os.path.join(out, "latest.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_probe_verdict_cases(self):
        v = collect.probe_verdict
        old, new = "2026-11-03 13:00", "2026-11-04 14:00"
        self.assertEqual(v(old, {"B numOfRows=9": old, "C _=타임스탬프": old, "D no-cache 헤더": old, "E 기준 재호출": old}), "source")
        self.assertEqual(v(old, {"B numOfRows=9": old, "C _=타임스탬프": new, "D no-cache 헤더": old, "E 기준 재호출": old}), "cache")
        # 시험 도중 새 값 도착: D, E 가 최신이어도 E(같은 주소)가 같이 최신이면 캐시가 아니다
        self.assertEqual(v(old, {"B numOfRows=9": old, "C _=타임스탬프": old, "D no-cache 헤더": new, "E 기준 재호출": new}), "updated")
        self.assertEqual(v(old, {"B numOfRows=9": None, "E 기준 재호출": None}), "error")

    def test_source_verdict_is_recorded_with_all_variants(self):
        calls = []

        def probe(key, code, secrets, extra, headers):
            calls.append((code, extra, headers))
            return WS_XML.format(t=self.STALE, v="1.0")
        with tempfile.TemporaryDirectory() as out:
            new, errors = self.run_with_probe(out, probe)
            self.assertEqual(errors, {})
            p = self.latest(out)["plants"]["UJ"]["probe"]
            self.assertEqual(p["verdict"], "source")
            self.assertEqual(p["baseline"], self.STALE)
            self.assertEqual(sorted(p["variants"]), ["B numOfRows=9", "C _=타임스탬프", "D no-cache 헤더", "E 기준 재호출"])
            self.assertEqual(p["checked_at_utc"], "2026-11-04T05:41:00Z")
        # 변형이 실제로 다르게 호출됐는지: 모두 UJ, B 는 numOfRows, C 는 알 수 없는 파라미터, D 는 no-cache 헤더, E 는 기준과 같음
        self.assertEqual([c[0] for c in calls], ["UJ"] * 4)
        self.assertEqual(calls[0][1], {"numOfRows": "9"})
        self.assertIn("_", calls[1][1])
        self.assertEqual(calls[2][2], {"Cache-Control": "no-cache", "Pragma": "no-cache"})
        self.assertEqual((calls[3][1], calls[3][2]), ({}, None))

    def test_cache_verdict_when_changed_url_returns_fresher_value(self):
        def probe(key, code, secrets, extra, headers):
            return WS_XML.format(t=self.FRESH if "_" in extra else self.STALE, v="1.0")
        with tempfile.TemporaryDirectory() as out:
            self.run_with_probe(out, probe)
            self.assertEqual(self.latest(out)["plants"]["UJ"]["probe"]["verdict"], "cache")

    def test_updated_verdict_when_repeat_call_also_returns_new_value(self):
        def probe(key, code, secrets, extra, headers):
            is_late = headers is not None or (extra == {} and headers is None)   # D, E (시험 도중 새 값 도착)
            return WS_XML.format(t=self.FRESH if is_late else self.STALE, v="1.0")
        with tempfile.TemporaryDirectory() as out:
            self.run_with_probe(out, probe)
            self.assertEqual(self.latest(out)["plants"]["UJ"]["probe"]["verdict"], "updated")

    def test_probe_result_is_reused_for_60_minutes_then_refreshed(self):
        calls = []

        def probe(key, code, secrets, extra, headers):
            calls.append(code)
            return WS_XML.format(t=self.STALE, v="1.0")
        # 시간이 지나도 다른 본부는 계속 수신 중인 상황: 그 본부들의 값은 매 회차 새로 갱신된다고 가정한다
        def later(key, plant, secrets):
            return WS_XML.format(t=self.STALE if plant == "UJ" else "2026-11-04 15:30", v="1.0")

        with tempfile.TemporaryDirectory() as out:
            self.run_with_probe(out, probe, now=NOW)
            self.assertEqual(len(calls), 4)
            first = self.latest(out)["plants"]["UJ"]["probe"]["checked_at_utc"]
            self.run_with_probe(out, probe, now=NOW + dt.timedelta(minutes=10), fetcher=later)
            self.run_with_probe(out, probe, now=NOW + dt.timedelta(minutes=59), fetcher=later)
            self.assertEqual(len(calls), 4, "60분 안에는 다시 호출하지 않는다")
            self.assertEqual(self.latest(out)["plants"]["UJ"]["probe"]["checked_at_utc"], first)
            self.run_with_probe(out, probe, now=NOW + dt.timedelta(minutes=61), fetcher=later)
            self.assertEqual(len(calls), 8, "60분이 지나면 다시 진단한다")

    def test_probe_not_reused_when_state_changed(self):
        calls = []

        def probe(key, code, secrets, extra, headers):
            calls.append(code)
            return WS_XML.format(t=self.STALE, v="1.0")
        with tempfile.TemporaryDirectory() as out:
            self.run_with_probe(out, probe, now=NOW)
            # 최신 시각이 달라지면(새 값 후 다시 멈춤) 이전 진단을 재사용하지 않는다
            self.run_with_probe(out, probe, now=NOW + dt.timedelta(minutes=10),
                                fetcher=self.fetcher(("UJ",), stale_time="2026-11-03 14:00"))
            self.assertEqual(len(calls), 8)

    def test_healthy_plants_are_never_probed_and_probe_is_cleared(self):
        calls = []

        def probe(key, code, secrets, extra, headers):
            calls.append(code)
            return WS_XML.format(t=self.STALE, v="1.0")
        with tempfile.TemporaryDirectory() as out:
            self.run_with_probe(out, probe, fetcher=self.fetcher(()))
            self.assertEqual(calls, [])
            latest = self.latest(out)["plants"]
            self.assertTrue(all("probe" not in v for v in latest.values()))
            # 멈췄다가 회복하면 이전 진단 기록이 남지 않는다
            self.run_with_probe(out, probe)
            self.assertIn("probe", self.latest(out)["plants"]["UJ"])
            self.run_with_probe(out, probe, now=NOW + dt.timedelta(minutes=10), fetcher=self.fetcher(()))
            self.assertNotIn("probe", self.latest(out)["plants"]["UJ"])

    def test_long_term_stale_plant_is_not_probed(self):
        calls = []

        def probe(key, code, secrets, extra, headers):
            calls.append(code)
            return WS_XML.format(t=self.TOO_OLD, v="1.0")
        with tempfile.TemporaryDirectory() as out:
            self.run_with_probe(out, probe, fetcher=self.fetcher(("KR",), stale_time=self.TOO_OLD))
            self.assertEqual(calls, [])
            self.assertNotIn("probe", self.latest(out)["plants"]["KR"])

    def test_probe_failures_do_not_break_collection(self):
        def probe(key, code, secrets, extra, headers):
            raise RuntimeError("HTTP 500")
        with tempfile.TemporaryDirectory() as out:
            new, errors = self.run_with_probe(out, probe)
            self.assertEqual(errors, {})                     # 수집 실패로 취급하지 않는다
            self.assertEqual(self.latest(out)["plants"]["UJ"]["probe"]["verdict"], "error")

    def test_no_probe_without_probe_fetcher(self):
        with tempfile.TemporaryDirectory() as out:
            collect.run("TESTKEY+a/b==", out, fetcher=self.fetcher(("UJ",)), sleep=lambda s: None, now=NOW)
            self.assertNotIn("probe", self.latest(out)["plants"]["UJ"])


if __name__ == "__main__":
    unittest.main()
