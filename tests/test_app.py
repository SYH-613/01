import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app import create_app


def call(app, method, path, body=""):
    status = []
    response = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(len(body.encode())), "wsgi.input": BytesIO(body.encode())}, lambda code, headers: status.append(code)))
    return status[0], response


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = self.enterContext(TemporaryDirectory())
        self.path = Path(self.tempdir) / "content.json"
        self.app = create_app(self.path)

    def test_content_can_be_updated_and_displayed(self):
        self.assertTrue(call(self.app, "POST", "/admin/settings", "site_title=%E6%96%B0%E5%90%8D%E7%A7%B0&tagline=%E6%96%B0")[0].startswith("303"))
        self.assertIn("新名称", call(self.app, "GET", "/")[1].decode())
        self.assertTrue(call(self.app, "POST", "/admin/sections", "title=%E5%8A%A8%E6%80%81&body=%E5%8F%91%E5%B8%83")[0].startswith("303"))
        self.assertEqual(json.loads(self.path.read_text())["sections"][-1]["title"], "动态")

    def test_unknown_section_returns_not_found(self):
        self.assertEqual(call(self.app, "POST", "/admin/sections/missing", "")[0], "404 Not Found")
