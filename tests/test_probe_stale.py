import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import probe_stale  # noqa: E402

BODY = ('<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode>'
        "<resultMsg>NORMAL SERVICE.</resultMsg></header><body><items>"
        "<item><expl>취수구-수온</expl><name>x</name><time>{t1}</time><value>1</value></item>"
        "<item><expl>배수구-수온</expl><name>y</name><time>{t2}</time><value>2</value></item>"
        "</items></body></response>")


def result(newest, status=200, code="00"):
    return {"status": status, "code": code, "items": 2, "newest": newest, "headers": {}, "error": None}


class ProbeTest(unittest.TestCase):
    def test_newest_time_takes_max_and_handles_empty(self):
        self.assertEqual(probe_stale.newest_time(BODY.format(t1="2026-11-07 13:00", t2="2026-11-07 12:55")), "2026-11-07 13:00")
        self.assertEqual(probe_stale.newest_time("<response><body><items/></body></response>"), "-")

    def test_pick_headers_keeps_cache_related_only(self):
        h = {"cache-control": "max-age=600", "x-cache": "HIT", "age": "12", "content-type": "x", "set-cookie": "s"}
        self.assertEqual(probe_stale.pick_headers(h), {"cache-control": "max-age=600", "x-cache": "HIT", "age": "12"})

    def test_verdict_source_when_all_variants_same(self):
        rs = [("A 기준", result("2026-11-07 13:00")), ("B", result("2026-11-07 13:00")), ("E", result("2026-11-07 13:00"))]
        kind, text = probe_stale.verdict(rs)
        self.assertEqual(kind, "source")
        self.assertIn("2026-11-07 13:00", text)

    def test_verdict_cache_when_a_variant_is_fresher(self):
        rs = [("A 기준", result("2026-11-07 13:00")), ("C _=타임스탬프", result("2026-11-08 17:00")), ("E 기준 재호출", result("2026-11-07 13:00"))]
        kind, text = probe_stale.verdict(rs)
        self.assertEqual(kind, "cache")
        self.assertIn("C _=타임스탬프=2026-11-08 17:00", text)

    def test_verdict_updated_when_repeat_call_is_also_fresher(self):
        """한빛 17:07 실제 사례: A,B 는 16:55, D,E 는 17:00 → 시험 도중 새 값이 도착한 것이지 캐시가 아니다."""
        rs = [("A 기준", result("2026-11-08 16:55")), ("B numOfRows=9", result("2026-11-08 16:55")),
              ("D no-cache 헤더", result("2026-11-08 17:00")), ("E 기준 재호출", result("2026-11-08 17:00"))]
        kind, text = probe_stale.verdict(rs)
        self.assertEqual(kind, "updated")
        self.assertIn("16:55 → 2026-11-08 17:00", text.replace("2026-11-08 16:55", "16:55"))

    def test_verdict_cache_requires_fresher_than_repeat_call(self):
        rs = [("A 기준", result("2026-11-08 16:55")), ("D no-cache 헤더", result("2026-11-08 17:00")),
              ("C _=타임스탬프", result("2026-11-08 17:05")), ("E 기준 재호출", result("2026-11-08 17:00"))]
        kind, text = probe_stale.verdict(rs)
        self.assertEqual(kind, "cache")
        self.assertIn("C _=타임스탬프=2026-11-08 17:05", text)
        self.assertNotIn("D no-cache", text)    # E 와 같은 값은 근거로 보지 않는다

    def test_verdict_error_when_not_enough_ok_responses(self):
        rs = [("A 기준", result("2026-11-07 13:00")), ("B", result("-", status=0, code="-"))]
        self.assertEqual(probe_stale.verdict(rs)[0], "error")

    def test_probe_plant_sends_all_variants_with_unique_cache_buster(self):
        seen = []

        def fake_fetch(key, secrets, code, extra=None, headers=None):
            seen.append((code, dict(extra or {}), dict(headers or {})))
            return result("2026-11-07 13:00")
        out = probe_stale.probe_plant("K", [], "UJ", fetch_fn=fake_fetch, sleep=lambda s: None)
        self.assertEqual([l for l, _ in out], ["A 기준", "B numOfRows=9", "C _=타임스탬프", "D no-cache 헤더", "E 기준 재호출"])
        self.assertEqual(seen[0][1], {})                                 # 기준은 수집기와 같은 주소
        self.assertEqual(seen[1][1], {"numOfRows": "9"})
        self.assertIn("_", seen[2][1])                                   # 캐시 키를 바꾸는 파라미터
        self.assertEqual(seen[3][2].get("Cache-Control"), "no-cache")
        self.assertTrue(all(c == "UJ" for c, _, _ in seen))

    def test_main_requires_key(self):
        old = os.environ.pop("DATA_GO_KR_SERVICE_KEY", None)
        try:
            self.assertEqual(probe_stale.main(), 1)
        finally:
            if old is not None:
                os.environ["DATA_GO_KR_SERVICE_KEY"] = old


if __name__ == "__main__":
    unittest.main()
