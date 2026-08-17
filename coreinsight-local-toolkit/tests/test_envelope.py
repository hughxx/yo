import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from coreinsight_local_toolkit.app import create_app
from coreinsight_local_toolkit.config import Settings


async def request(app, method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b''
    sent = []
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    scope = {
        'type': 'http', 'asgi': {'version': '3.0'},
        'http_version': '1.1', 'method': method, 'scheme': 'http',
        'path': path, 'raw_path': path.encode(), 'query_string': b'',
        'root_path': '', 'headers': [(b'content-type', b'application/json')],
        'client': ('127.0.0.1', 12345), 'server': ('127.0.0.1', 17831),
    }
    await app(scope, receive, send)
    start = next(item for item in sent if item['type'] == 'http.response.start')
    raw = b''.join(item.get('body', b'') for item in sent
                   if item['type'] == 'http.response.body')
    return start['status'], json.loads(raw)


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(
            data_dir=Path(self.temporary.name), update_enabled=False))

    def tearDown(self):
        self.app.router.on_shutdown[0]()
        self.temporary.cleanup()

    def test_health_uses_success_envelope(self):
        status, body = asyncio.run(request(self.app, 'GET', '/health'))
        self.assertEqual(200, status)
        self.assertEqual(200, body['code'])
        self.assertEqual('ok', body['msg'])
        self.assertEqual('coreinsight-local-toolkit', body['data']['service'])

    def test_validation_error_uses_error_envelope(self):
        status, body = asyncio.run(request(
            self.app, 'POST', '/welink/group/add', {}))
        self.assertEqual(422, status)
        self.assertEqual(422, body['code'])
        self.assertTrue(body['msg'])
        self.assertIsNone(body['data'])

    def test_created_conflict_and_no_content_are_enveloped(self):
        payload = {'groupId': 'g1', 'name': 'Group One'}
        status, body = asyncio.run(request(
            self.app, 'POST', '/welink/group/add', payload))
        self.assertEqual(200, status)
        self.assertEqual(200, body['code'])
        self.assertEqual('g1', body['data']['groupId'])

        status, body = asyncio.run(request(
            self.app, 'POST', '/welink/group/add', payload))
        self.assertEqual(409, status)
        self.assertEqual(409, body['code'])
        self.assertIsNone(body['data'])
        self.assertIn('已添加', body['msg'])

        status, body = asyncio.run(request(
            self.app, 'DELETE', '/welink/group/delete', {'groupId': 'g1'}))
        self.assertEqual(200, status)
        self.assertEqual({'code': 200, 'msg': 'ok', 'data': None}, body)
