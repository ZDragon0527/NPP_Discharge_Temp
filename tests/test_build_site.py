import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_site  # noqa: E402


class BuildSiteTest(unittest.TestCase):
    def test_build_copies_web_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "site")
            build_site.build(out)
            for name in ("index.html", "app.js", "logic.js", "style.css", "sw.js"):
                self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
            self.assertFalse(os.path.exists(os.path.join(out, "data")))  # 측정 데이터는 포함하지 않는다

    def test_rebuild_replaces_existing_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "site")
            os.makedirs(out)
            open(os.path.join(out, "stale.txt"), "w").close()
            build_site.build(out)
            self.assertFalse(os.path.exists(os.path.join(out, "stale.txt")))

    def test_missing_index_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                build_site.build(os.path.join(tmp, "site"), web_dir=tmp)


if __name__ == "__main__":
    unittest.main()
