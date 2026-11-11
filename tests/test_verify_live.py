import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import verify_live  # noqa: E402

EXPECTED = b"console.log('v2');"


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run(results, **kw):
    clock = FakeClock()
    logs, calls = [], {"n": 0}

    def fetch(_base, _path):
        i = min(calls["n"], len(results) - 1)
        calls["n"] += 1
        return results[i]

    ok = verify_live.verify("https://x.github.io/repo/", "sw.js", EXPECTED, fetch=fetch,
                            sleep=clock.sleep, clock=clock.now, log=logs.append, **kw)
    return ok, logs, calls["n"]


class VerifyLiveTest(unittest.TestCase):
    def test_pass_when_same(self):
        ok, logs, n = run([(EXPECTED, None)])
        self.assertTrue(ok)
        self.assertEqual(n, 1)
        self.assertTrue(any("통과" in l for l in logs))

    def test_pass_after_retry(self):
        ok, _, n = run([(b"old", None), (b"old", None), (EXPECTED, None)], timeout=150, interval=15)
        self.assertTrue(ok)
        self.assertEqual(n, 3)

    def test_fail_when_never_updated(self):
        ok, logs, n = run([(b"old", None)], timeout=60, interval=15)
        self.assertFalse(ok)
        self.assertGreaterEqual(n, 4)
        self.assertTrue(any("::error::" in l for l in logs))

    def test_fail_on_fetch_errors(self):
        ok, logs, _ = run([(None, "HTTP 404")], timeout=30, interval=15)
        self.assertFalse(ok)
        self.assertTrue(any("HTTP 404" in l for l in logs))


if __name__ == "__main__":
    unittest.main()
