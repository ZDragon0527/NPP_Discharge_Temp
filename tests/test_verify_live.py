import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import verify_live  # noqa: E402


def doc(updated, ws="2026-11-06 07:10"):
    return {"updated_at_utc": updated, "plants": {
        "WS": {"items": [{"time": ws}, {"time": ws}]},
        "KR": {"items": [{"time": "2026-07-07 10:19"}]},
    }}


EXPECTED = doc("2026-11-05T22:40:16Z")


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run(fetch_results, **kw):
    """fetch_results: 호출 순서대로 (dict|None, 사유) 목록. 다 쓰면 마지막 값 반복."""
    clock = FakeClock()
    logs, calls = [], {"n": 0}

    def fetch(_url):
        i = min(calls["n"], len(fetch_results) - 1)
        calls["n"] += 1
        return fetch_results[i]

    ok = verify_live.verify("https://x.github.io/repo/", EXPECTED, fetch=fetch, sleep=clock.sleep,
                            clock=clock.now, log=logs.append, **kw)
    return ok, logs, calls["n"]


class VerifyLiveTest(unittest.TestCase):
    def test_lag_minutes(self):
        self.assertEqual(verify_live.lag_minutes(doc("2026-11-05T22:40:16Z"), EXPECTED), 0)
        self.assertEqual(verify_live.lag_minutes(doc("2026-11-05T22:30:16Z"), EXPECTED), 10)
        self.assertEqual(verify_live.lag_minutes(doc("2026-11-05T14:40:18Z"), EXPECTED), 479)
        self.assertEqual(verify_live.lag_minutes(doc("2026-11-05T22:50:00Z"), EXPECTED), 0)  # 앞서 있어도 0

    def test_pass_when_equal(self):
        ok, logs, n = run([(doc("2026-11-05T22:40:16Z"), None)])
        self.assertTrue(ok)
        self.assertEqual(n, 1)
        self.assertTrue(any("통과" in l for l in logs))

    def test_pass_within_cdn_cache_window(self):
        """CDN 이 최대 10분 캐시하므로 10분 뒤처짐은 정상으로 본다(오경보 방지)."""
        ok, _, n = run([(doc("2026-11-05T22:30:16Z"), None)])
        self.assertTrue(ok)
        self.assertEqual(n, 1)

    def test_fail_when_frozen_for_hours(self):
        """2026-11-05 사고 재현: 공개 사이트가 8시간 전 값에 멈춤."""
        ok, logs, n = run([(doc("2026-11-05T14:40:18Z", ws="2026-11-05 19:20"), None)], timeout=150, interval=15)
        self.assertFalse(ok)
        self.assertGreater(n, 1)  # 제한 시간까지 다시 읽어 봄
        text = "\n".join(logs)
        self.assertIn("::error::", text)
        self.assertIn("479분", text)
        self.assertIn("2026-11-05 19:20", text)       # 공개 사이트 쪽 본부별 최신 시각
        self.assertIn("2026-11-06 07:10", text)       # 배포본 쪽

    def test_passes_when_site_catches_up_later(self):
        stale = (doc("2026-11-05T14:40:18Z"), None)
        fresh = (doc("2026-11-05T22:40:16Z"), None)
        ok, _, n = run([stale, stale, fresh])
        self.assertTrue(ok)
        self.assertEqual(n, 3)

    def test_fetch_errors_then_recovery(self):
        ok, logs, n = run([(None, "연결 실패: timed out"), (doc("2026-11-05T22:40:16Z"), None)])
        self.assertTrue(ok)
        self.assertEqual(n, 2)
        self.assertTrue(any("읽기 실패" in l for l in logs))

    def test_fail_when_always_unreachable(self):
        ok, logs, _ = run([(None, "HTTP 404")], timeout=60, interval=15)
        self.assertFalse(ok)
        self.assertTrue(any("::error::" in l and "HTTP 404" in l for l in logs))

    def test_bad_updated_at_is_failure_not_crash(self):
        ok, logs, _ = run([({"updated_at_utc": "이상한 값", "plants": {}}, None)], timeout=30, interval=15)
        self.assertFalse(ok)
        self.assertTrue(any("해석 실패" in l for l in logs))

    def test_newest_times(self):
        self.assertEqual(verify_live.newest_times(doc("2026-11-05T22:40:16Z")),
                         {"WS": "2026-11-06 07:10", "KR": "2026-07-07 10:19"})
        self.assertEqual(verify_live.newest_times({"plants": {"WS": {"items": []}}}), {"WS": "-"})

    def test_main_rejects_missing_expected_file(self):
        self.assertEqual(verify_live.main(["--url", "https://x/", "--expected", "/nonexistent/latest.json"]), 1)


if __name__ == "__main__":
    unittest.main()
