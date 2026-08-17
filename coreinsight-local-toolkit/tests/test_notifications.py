import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.environment import EnvironmentManager, TESTING
from coreinsight_local_toolkit.notifications import MessageNotifier


class MessageNotifierTests(unittest.TestCase):
    def settings(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Settings(
            data_dir=Path(directory.name),
            notification_url='http://notify/message',
            portal_url='https://coreinsight.rnd.huawei.com',
            experience_create_url=(
                'https://coreinsight.rnd.huawei.com/experience/create'))

    def test_direct_notification_uses_multipart_and_environment_links(self):
        settings = self.settings()
        EnvironmentManager(settings.data_dir).set(TESTING)
        session = Mock()
        response = Mock()
        session.post.return_value = response
        notifier = MessageNotifier(settings, session=session)

        self.assertTrue(notifier.notify('w00899061', 'direct', [
            {'docId': 'doc/1', 'title': '定位连接失败'},
            {'docId': 'doc-2', 'title': '修复超时'},
        ]))

        call = session.post.call_args
        self.assertEqual('http://notify/message', call.args[0])
        self.assertEqual(
            '["w00899061"]',
            call.kwargs['files']['target_accounts'][1])
        text = call.kwargs['files']['text'][1]
        self.assertIn('定位连接失败', text)
        self.assertIn(
            'https://coreinsight-beta.rnd.huawei.com/experience/doc%2F1', text)
        self.assertIn(
            'https://coreinsight-beta.rnd.huawei.com/experience/doc-2', text)
        response.raise_for_status.assert_called_once()

    def test_draft_notification_points_to_pending_experience_page(self):
        settings = self.settings()
        session = Mock()
        session.post.return_value = Mock()
        notifier = MessageNotifier(settings, session=session)
        notifier.notify('u1', 'draft', [
            {'docId': 'draft-1', 'title': '待确认标题'},
        ])
        text = session.post.call_args.kwargs['files']['text'][1]
        self.assertIn('待确认经验', text)
        self.assertIn('待确认标题', text)
        self.assertIn(
            'https://coreinsight.rnd.huawei.com/experience/create', text)

    def test_notification_failure_is_best_effort(self):
        settings = self.settings()
        session = Mock()
        session.post.side_effect = RuntimeError('offline')
        notifier = MessageNotifier(settings, session=session)
        self.assertFalse(notifier.notify(
            'u1', 'direct', [{'docId': '1', 'title': '标题'}]))

    def test_empty_result_does_not_send(self):
        settings = self.settings()
        session = Mock()
        notifier = MessageNotifier(settings, session=session)
        self.assertFalse(notifier.notify('u1', 'direct', []))
        session.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
