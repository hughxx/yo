import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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
                portal = client.get('/portal', follow_redirects=False)
        self.assertEqual(200, page.status_code)
        self.assertIn('Local Toolkit 已启动', page.text)
        self.assertIn('本地服务器已就绪，Toolkit将持续在后台运行', page.text)
        self.assertIn('<strong>桌面悬浮入口</strong>', page.text)
        self.assertIn('<strong>后台持续运行</strong>', page.text)
        self.assertIn('<strong>任务栏托盘</strong>', page.text)
        self.assertIn('href="/portal"', page.text)
        self.assertEqual(200, icon.status_code)
        self.assertIn('image/svg+xml', icon.headers['content-type'])
        self.assertEqual(307, portal.status_code)
        self.assertEqual(
            'https://coreinsight.rnd.huawei.com', portal.headers['location'])

    def test_email_demo_and_configuration_endpoints_are_available(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(
                data_dir=Path(directory), update_enabled=False))
            with TestClient(app) as client:
                page = client.get('/demo/')
                capabilities = client.get('/capabilities').json()
                saved = client.put('/email/config', json={
                    'folders': ['Mailbox\\Inbox'],
                    'rules': [{
                        'name': 'technical',
                        'subjectKeywords': ['failure'],
                    }],
                    'blacklist': [],
                    'extractMode': 'direct',
                    'uploadBy': 'u1',
                }).json()
        self.assertEqual(200, page.status_code)
        self.assertIn('id="email-demo"', page.text)
        self.assertIn('id="email-extract-modal"', page.text)
        self.assertIn('id="email-schedule-modal"', page.text)
        self.assertIn('class="email-search-combined"', page.text)
        self.assertIn('id="email-rules-popover"', page.text)
        self.assertIn('id="email-rule-warning"', page.text)
        self.assertIn('尚未配置有效的提取规则', page.text)
        self.assertIn('id="email-start-menu"', page.text)
        self.assertNotIn('class="outlook-card"', page.text)
        self.assertNotIn('class="email-extract-bar"', page.text)
        self.assertEqual(
            ['prompt', 'skill'],
            capabilities['data']['modelResources'])
        self.assertEqual(['Mailbox\\Inbox'], saved['data']['folders'])
        self.assertTrue(saved['data']['rules'][0]['id'])

    def test_model_configuration_endpoint_validates_request(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(
                data_dir=Path(directory), update_enabled=False))
            with TestClient(app) as client:
                model_config = client.get('/model/config')
                model_test = client.post('/model/test', json={})
                removed = client.get('/email/skill/list')
        self.assertEqual(404, model_config.status_code)
        self.assertEqual(422, model_test.status_code)
        self.assertEqual(404, removed.status_code)

    def test_model_test_page_is_served(self):
        with TestClient(create_app(Settings(data_dir=Path(tempfile.mkdtemp())))) as client:
            page = client.get('/model-test')
        self.assertEqual(200, page.status_code)
        self.assertIn('AI 连通性测试', page.text)

    def test_email_list_is_an_async_task_with_a_status_endpoint(self):
        row = {
            "id": "mail-1", "subject": "Failure", "senderName": "Alice",
            "senderEmail": "alice@example.com",
            "receivedTime": "2026-09-10 10:00:00", "timestamp": 1,
            "conversationTopic": "Failure", "hasAttachments": False,
        }
        with tempfile.TemporaryDirectory() as directory, patch(
                "coreinsight_local_toolkit.outlook.OutlookClient.list_messages",
                return_value=[row]):
            app = create_app(Settings(
                data_dir=Path(directory), update_enabled=False))
            with TestClient(app) as client:
                started = client.post('/email/message/list', json={
                    'folders': ['Mailbox\\Inbox', 'Mailbox\\Project'],
                }).json()['data']
                for _ in range(100):
                    response = client.get(
                        '/email/message/list/status',
                        params={'taskId': started['taskId']})
                    current = response.json()['data']
                    if not current['running']:
                        break
                    time.sleep(.01)
                removed = client.post('/email/message/scan', json={
                    'folders': ['Mailbox\\Inbox'],
                })

        self.assertEqual('done', current['status'])
        self.assertEqual(['mail-1'], [item['id'] for item in current['items']])
        self.assertEqual(404, removed.status_code)

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
