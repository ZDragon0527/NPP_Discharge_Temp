import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import check_data_dir as chk  # noqa: E402

NOW = dt.datetime(2026, 11, 11, 3, 0, tzinfo=dt.timezone.utc)


def make(tmp, rows_by_day, latest=True, history=True):
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    for day, n in rows_by_day.items():
        with open(os.path.join(tmp, "data", f"{day}.csv"), "w", encoding="utf-8") as f:
            f.write("collected_at_utc,plant,time_kst,name,expl,value\n")
            for i in range(n):
                f.write(f"x,WS,{day} 10:{i:02d},t,취수구-수온,19\n")
    if latest:
        json.dump({"plants": {"WS": {}}, "updated_at_utc": "2026-11-11T03:00:00Z"}, open(os.path.join(tmp, "latest.json"), "w"))
    if history:
        json.dump({"plants": {}, "generated_at_utc": "2026-11-11T03:00:00Z"}, open(os.path.join(tmp, "history.json"), "w"))


class CheckTest(unittest.TestCase):
    def test_pass_when_grows(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, {"2026-11-10": 5, "2026-11-11": 3})
            self.assertEqual(chk.verify(tmp, {"2026-11-10.csv": 5, "2026-11-11.csv": 2}, 120, NOW), [])

    def test_fail_when_rows_shrink_or_file_vanishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, {"2026-11-11": 1})
            p = chk.verify(tmp, {"2026-11-10.csv": 5, "2026-11-11.csv": 2}, 120, NOW)
            self.assertEqual(len(p), 2)
            self.assertTrue(any("사라졌다" in x for x in p))
            self.assertTrue(any("줄었다" in x for x in p))

    def test_old_files_outside_keep_window_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, {"2026-11-11": 2})
            self.assertEqual(chk.verify(tmp, {"2026-05-01.csv": 9}, 120, NOW), [])

    def test_missing_json_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, {}, latest=False, history=False)
            self.assertEqual(len(chk.verify(tmp, {}, 0, NOW)), 2)

    def test_cli_snapshot_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, {"2026-11-11": 3})
            prev = os.path.join(tmp, "prev.json")
            self.assertEqual(chk.main(["snapshot", "--data-dir", tmp, "--out", prev]), 0)
            self.assertEqual(json.load(open(prev)), {"2026-11-11.csv": 3})
            self.assertEqual(chk.main(["verify", "--data-dir", tmp, "--prev", prev]), 0)
            make(tmp, {"2026-11-11": 1})
            self.assertEqual(chk.main(["verify", "--data-dir", tmp, "--prev", prev]), 1)
            self.assertEqual(chk.main(["verify", "--data-dir", tmp, "--prev", os.path.join(tmp, "none.json")]), 1)


if __name__ == "__main__":
    unittest.main()
