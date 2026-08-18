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

    def test_email_demo_and_configuration_endpoints_are_available(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(
                data_dir=Path(directory), update_enabled=False))
            with TestClient(app) as client:
                page = client.get('/demo/')
                skills = client.get('/email/skill/list').json()
                saved = client.put('/email/config', json={
                    'folders': ['Mailbox\\Inbox'],
                    'rules': [{
                        'name': 'technical',
                        'subjectKeywords': ['failure'],
                    }],
                    'blacklist': [],
                    'skillId': 'email-experience-extractor',
                    'extractMode': 'direct',
                    'uploadBy': 'u1',
                }).json()
        self.assertEqual(200, page.status_code)
        self.assertIn('id="email-demo"', page.text)
        self.assertIn('id="email-extract-modal"', page.text)
        self.assertIn('id="email-schedule-modal"', page.text)
        self.assertIn('class="email-search-combined"', page.text)
        self.assertIn('id="email-rules-popover"', page.text)
        self.assertIn('id="email-start-menu"', page.text)
        self.assertNotIn('class="email-extract-bar"', page.text)
        self.assertEqual('email-experience-extractor', skills['data'][0]['id'])
        self.assertEqual(['Mailbox\\Inbox'], saved['data']['folders'])
        self.assertTrue(saved['data']['rules'][0]['id'])

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
