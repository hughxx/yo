import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from coreinsight_local_toolkit.app import create_app
from coreinsight_local_toolkit.config import Settings


class AppCorsTests(unittest.TestCase):
    def test_welcome_page_and_icon_are_served(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(
                data_dir=Path(directory), update_enabled=False))
            with TestClient(app) as client:
                page = client.get('/welcome/')
                icon = client.get('/welcome/icon.svg')
        self.assertEqual(200, page.status_code)
        self.assertIn('Local Toolkit 已启动', page.text)
        self.assertIn('桌面悬浮 Logo', page.text)
        self.assertEqual(200, icon.status_code)
        self.assertIn('image/svg+xml', icon.headers['content-type'])

    def test_local_huawei_origin_can_preflight_private_network_request(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(
                data_dir=Path(directory), update_enabled=False))
            with TestClient(app) as client:
                response = client.options(
                    "/welink/message/list",
                    headers={
                        "Origin": "http://localhost.huawei.com:8080",
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "content-type",
                        "Access-Control-Request-Private-Network": "true",
                    },
                )
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "http://localhost.huawei.com:8080",
            response.headers["access-control-allow-origin"])
        self.assertEqual(
            "true", response.headers["access-control-allow-private-network"])


if __name__ == "__main__":
    unittest.main()
