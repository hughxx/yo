import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.drafts import DraftClient


class DraftClientTests(unittest.TestCase):
    def settings(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Settings(
            data_dir=Path(directory.name),
            draft_api_url='https://coreinsight.rnd.huawei.com/chat')

    @staticmethod
    def response(status=200, body=None):
        response = Mock()
        response.status_code = status
        response.json.return_value = body or {
            'code': 200, 'msg': 'success', 'data': {'id': 'draft-1'}}
        return response

    def test_create_posts_complete_contract(self):
        session = Mock()
        session.post.return_value = self.response()
        client = DraftClient(self.settings(), session=session)
        generated = Mock(hex='draft-1')
        with patch('coreinsight_local_toolkit.drafts.uuid.uuid4', return_value=generated):
            doc_id = client.save({
                'operation': 'create', 'title': '标题', 'summary': '正文',
                'experience': '剧本', 'rag_search_text': '不会发送',
            }, 'w00899061')
        self.assertEqual('draft-1', doc_id)
        session.post.assert_called_once_with(
            'https://coreinsight.rnd.huawei.com/chat/experience/draft/create',
            json={
                'doc_id': 'draft-1', 'user_id': 'w00899061',
                'scene': 'WeLink问题定位经验', 'scene_id': '251',
                'title': '标题', 'summary': '正文', 'experience': '剧本',
            }, timeout=60, verify=False)

    def test_update_puts_only_supported_explicit_fields(self):
        session = Mock()
        session.put.return_value = self.response(
            body={'code': 0, 'msg': 'success', 'data': {'id': 'draft/1'}})
        client = DraftClient(self.settings(), session=session)
        doc_id = client.save({
            'operation': 'update', 'doc_id': 'draft/1',
            'summary': '合并后的正文', 'rag_search_text': '不会发送',
        }, 'w00899061')
        self.assertEqual('draft/1', doc_id)
        session.put.assert_called_once_with(
            'https://coreinsight.rnd.huawei.com/chat/experience/draft/draft%2F1',
            json={'user_id': 'w00899061', 'summary': '合并后的正文'},
            timeout=60, verify=False)
        session.post.assert_not_called()

    def test_update_not_found_never_falls_back_to_create(self):
        session = Mock()
        session.put.return_value = self.response(
            404, {'code': 0, 'msg': '草稿不存在', 'data': None})
        client = DraftClient(self.settings(), session=session)
        with self.assertRaisesRegex(RuntimeError, '草稿不存在'):
            client.save({'operation': 'update', 'doc_id': 'missing',
                         'title': '标题'}, 'u1')
        session.post.assert_not_called()

    def test_success_requires_data_id_even_when_code_is_zero(self):
        session = Mock()
        session.post.return_value = self.response(
            200, {'code': 0, 'msg': '创建失败', 'data': None})
        client = DraftClient(self.settings(), session=session)
        with self.assertRaisesRegex(RuntimeError, '创建失败'):
            client.save({'operation': 'create', 'title': 't',
                         'summary': 's', 'experience': 'e'}, 'u1')

    def test_legacy_code_zero_is_still_accepted(self):
        session = Mock()
        session.post.return_value = self.response(
            200, {'code': 0, 'msg': 'success', 'data': {'id': 'draft-1'}})
        client = DraftClient(self.settings(), session=session)
        generated = Mock(hex='draft-1')
        with patch('coreinsight_local_toolkit.drafts.uuid.uuid4',
                   return_value=generated):
            doc_id = client.save({
                'operation': 'create', 'title': 't',
                'summary': 's', 'experience': 'e',
            }, 'u1')
        self.assertEqual('draft-1', doc_id)

    def test_operation_and_shape_are_strict(self):
        client = DraftClient(self.settings(), session=Mock())
        with self.assertRaisesRegex(ValueError, 'operation'):
            client.save({'title': 't'}, 'u1')
        with self.assertRaisesRegex(ValueError, '不能携带 doc_id'):
            client.save({'operation': 'create', 'doc_id': 'x', 'title': 't',
                         'summary': 's', 'experience': 'e'}, 'u1')
        with self.assertRaisesRegex(ValueError, '必须携带 doc_id'):
            client.save({'operation': 'update', 'title': 't'}, 'u1')


if __name__ == '__main__':
    unittest.main()
