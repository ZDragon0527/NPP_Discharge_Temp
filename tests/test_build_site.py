import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_site  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class BuildSiteTest(unittest.TestCase):
    def test_build_copies_web_and_latest_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data-out")
            os.makedirs(data)
            with open(os.path.join(FIXTURE_DIR, "latest.sample.json"), encoding="utf-8") as f:
                content = f.read()
            with open(os.path.join(data, "latest.json"), "w", encoding="utf-8") as f:
                f.write(content)
            # 이력 CSV 는 배포물에 들어가면 안 된다
            os.makedirs(os.path.join(data, "data"))
            open(os.path.join(data, "data", "2026-11-04.csv"), "w").close()
            out = os.path.join(tmp, "site")
            build_site.build(data, out)
            for name in ("index.html", "app.js", "logic.js", "style.css"):
                self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
            self.assertTrue(os.path.isfile(os.path.join(out, "data", "latest.json")))
            self.assertFalse(os.path.exists(os.path.join(out, "data", "2026-11-04.csv")))
            with open(os.path.join(out, "data", "latest.json"), encoding="utf-8") as f:
                self.assertIn("WS", json.load(f)["plants"])

    def test_missing_or_broken_latest_json_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                build_site.build(tmp, os.path.join(tmp, "site"))
            with open(os.path.join(tmp, "latest.json"), "w") as f:
                f.write("{broken")
            with self.assertRaises(ValueError):
                build_site.build(tmp, os.path.join(tmp, "site"))
            self.assertFalse(os.path.exists(os.path.join(tmp, "site")))

    def test_rebuild_replaces_old_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "latest.json"), "w") as f:
                f.write("{}")
            out = os.path.join(tmp, "site")
            build_site.build(tmp, out)
            stale = os.path.join(out, "stale.txt")
            open(stale, "w").close()
            build_site.build(tmp, out)
            self.assertFalse(os.path.exists(stale))


if __name__ == "__main__":
    unittest.main()
