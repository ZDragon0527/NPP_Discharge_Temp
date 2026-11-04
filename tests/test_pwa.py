"""설치형 웹앱(PWA) 정적 검증: 매니페스트·아이콘·서비스 워커 캐시 목록이 서로 맞는지 확인한다.
캐시 목록(SHELL)에 없는 파일이 하나라도 있으면 서비스 워커 설치 전체가 실패하므로 반드시 검사한다."""
import json
import os
import re
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
WEB = os.path.join(HERE, "..", "web")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import build_site  # noqa: E402


def read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return f.read()


def png_size(path):
    with open(path, "rb") as f:
        d = f.read(24)
    assert d[:8] == b"\x89PNG\r\n\x1a\n", f"PNG 아님: {path}"
    return struct.unpack(">II", d[16:24])


class PwaTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(read("manifest.webmanifest"))

    def test_manifest_required_fields(self):
        m = self.manifest
        for k in ("name", "short_name", "start_url", "scope", "display", "icons", "theme_color", "background_color"):
            self.assertIn(k, m, k)
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["lang"], "ko")
        self.assertLessEqual(len(m["short_name"]), 12)

    def test_paths_are_relative_for_subpath_hosting(self):
        """GitHub Pages 는 /저장소이름/ 아래에서 서비스되므로 '/' 로 시작하는 절대 경로를 쓰면 깨진다."""
        m = self.manifest
        self.assertFalse(m["start_url"].startswith("/"))
        self.assertFalse(m["scope"].startswith("/"))
        for icon in m["icons"]:
            self.assertFalse(icon["src"].startswith("/"), icon["src"])
        html = read("index.html")
        for attr in re.findall(r'(?:href|src)="([^"]+)"', html):
            if attr.startswith(("data:", "http", "#")):
                continue
            self.assertFalse(attr.startswith("/"), f"index.html 절대 경로: {attr}")
        self.assertNotIn("id", m, "id 를 상대 경로로 두면 github.io 의 다른 사이트와 앱 식별자가 겹칠 수 있다")

    def test_icons_exist_with_declared_sizes(self):
        purposes = []
        for icon in self.manifest["icons"]:
            path = os.path.join(WEB, icon["src"])
            self.assertTrue(os.path.isfile(path), icon["src"])
            w, h = png_size(path)
            self.assertEqual(f"{w}x{h}", icon["sizes"], icon["src"])
            purposes.append((icon["purpose"], w))
        self.assertIn(("any", 192), purposes)
        self.assertIn(("any", 512), purposes)
        self.assertIn(("maskable", 512), purposes)

    def test_apple_touch_icon(self):
        html = read("index.html")
        m = re.search(r'rel="apple-touch-icon" href="([^"]+)"', html)
        self.assertIsNotNone(m)
        self.assertEqual(png_size(os.path.join(WEB, m.group(1))), (180, 180))
        self.assertIn('rel="manifest" href="manifest.webmanifest"', html)
        self.assertIn('name="theme-color"', html)

    def test_service_worker_shell_files_exist(self):
        sw = read("sw.js")
        shell = re.search(r"var SHELL = \[(.*?)\];", sw, re.S)
        self.assertIsNotNone(shell)
        entries = re.findall(r"'([^']+)'", shell.group(1))
        self.assertGreaterEqual(len(entries), 8)
        for e in entries:
            rel = "index.html" if e == "./" else e
            self.assertTrue(os.path.isfile(os.path.join(WEB, rel)), f"SHELL 파일 없음: {e}")
        # 화면이 실제로 쓰는 스크립트·스타일이 모두 캐시 목록에 있어야 오프라인에서 동작한다
        html = read("index.html")
        used = re.findall(r'<script src="([^"]+)"', html) + re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
        for u in used:
            self.assertIn(u, entries, f"오프라인용 캐시 목록에 빠짐: {u}")

    def test_service_worker_does_not_touch_other_sites_caches(self):
        sw = read("sw.js")
        self.assertIn("CACHE_PREFIX = 'npp-discharge-'", sw)
        self.assertRegex(sw, r"k\.indexOf\(CACHE_PREFIX\) === 0")
        self.assertIn("url.origin !== self.location.origin", sw)   # 외부 요청은 가로채지 않음
        self.assertIn("request.method !== 'GET'", sw)

    def test_build_includes_pwa_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            with open(os.path.join(data, "latest.json"), "w") as f:
                f.write("{}")
            out = os.path.join(tmp, "site")
            build_site.build(data, out)
            for name in ("manifest.webmanifest", "sw.js", "icons/icon-192.png", "icons/icon-512.png",
                         "icons/icon-maskable-512.png", "icons/apple-touch-icon.png", "icons/icon.svg"):
                self.assertTrue(os.path.isfile(os.path.join(out, name)), name)


if __name__ == "__main__":
    unittest.main()
