import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from coreinsight_local_toolkit.extraction import ExtractionRuntime
from coreinsight_local_toolkit.models import ExtractRequest, GroupCreate
from coreinsight_local_toolkit.store import GroupStore


class FakeHistory:
    def fetch_page(self, group_id, start_ms, end_ms, cursor, limit):
        if not cursor:
            return {'items': [{'id': '3'}, {'id': '2'}],
                    'nextCursor': '2', 'hasMore': True}
        return {'items': [{'id': '1'}], 'nextCursor': '', 'hasMore': False}


class BoundaryHistory:
    def fetch_page(self, group_id, start_ms, end_ms, cursor, limit):
        return {'items': [
            {'id': 'boundary', 'timestamp': start_ms},
            {'id': 'new', 'timestamp': start_ms + 1},
        ], 'nextCursor': '', 'hasMore': False}


class FakeProcessor:
    def __init__(self):
        self.calls = []

    def validate(self, upload_by, skill_id=None, extract_mode="direct"):
        pass

    def process(self, *args, **kwargs):
        self.calls.append(args)
        return {'docId': 'doc-1', 'title': 'Test title'}


class BlockingProcessor(FakeProcessor):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def process(self, *args, **kwargs):
        self.calls.append(args)
        self.entered.set()
        self.release.wait(2)
        return {'docId': 'doc-1', 'title': 'Test title'}


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, *args):
        self.calls.append(args)
        return True


class ExtractionRuntimeTests(unittest.TestCase):
    def test_different_groups_queue_and_same_group_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = GroupStore(Path(directory))
            groups.add(GroupCreate(groupId='g1'))
            groups.add(GroupCreate(groupId='g2'))
            processor = BlockingProcessor()
            runtime = ExtractionRuntime(FakeHistory(), groups, processor, 'u1')
            payload1 = ExtractRequest(groupId='g1', uploadBy='u1')
            payload2 = ExtractRequest(groupId='g2', uploadBy='u1')
            first = runtime.start(payload1, 0, 10)
            self.assertTrue(processor.entered.wait(1))
            second = runtime.start(payload2, 0, 10)
            self.assertEqual('queued', runtime.status(task_id=second['taskId'])['status'])
            with self.assertRaisesRegex(RuntimeError, '该群组已有'):
                runtime.start(payload1, 0, 10)
            cancelled = runtime.cancel(task_id=second['taskId'])
            self.assertEqual('cancelled', cancelled['status'])
            self.assertEqual('idle', groups.get('g2').status)
            processor.release.set()
            for _ in range(100):
                if not runtime.status(task_id=first['taskId'])['running']:
                    break
                time.sleep(0.01)
            self.assertEqual('done', runtime.status(task_id=first['taskId'])['status'])
            self.assertEqual(2, len(runtime.tasks()))
            runtime.close()

    def test_all_mode_filters_by_msg_id_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = GroupStore(Path(directory))
            groups.add(GroupCreate(groupId='g1'))
            processor = FakeProcessor()
            runtime = ExtractionRuntime(FakeHistory(), groups, processor, 'u1')
            payload = ExtractRequest(
                groupId='g1', uploadBy='u1', skillId='welink-experience-extractor',
                selection={'mode': 'all', 'excludedMessageIds': ['2']})
            runtime.start(payload, 0, 10)
            for _ in range(100):
                if not runtime.status()['running']:
                    break
                time.sleep(0.01)
            self.assertEqual(['3', '1'], [item['id'] for item in processor.calls[0][0]])
            self.assertEqual(('welink-experience-extractor', 'u1'), processor.calls[0][1:3])
            self.assertEqual('done', runtime.status()['status'])
            self.assertEqual('idle', groups.get('g1').status)
            runtime.close()

    def test_scheduled_window_excludes_the_previous_cursor_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = GroupStore(Path(directory))
            groups.add(GroupCreate(groupId='g1'))
            processor = FakeProcessor()
            runtime = ExtractionRuntime(BoundaryHistory(), groups, processor, 'u1')
            payload = ExtractRequest(groupId='g1', uploadBy='u1')
            task = runtime.start(payload, 100, 200, scheduled=True)
            for _ in range(100):
                if not runtime.status(task_id=task['taskId'])['running']:
                    break
                time.sleep(0.01)
            self.assertEqual(['new'], [item['id'] for item in processor.calls[0][0]])
            runtime.close()

    def test_success_notifies_uploading_user_with_experience_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = GroupStore(Path(directory))
            groups.add(GroupCreate(groupId='g1'))
            processor = FakeProcessor()
            processor.process = Mock(return_value={
                'docId': 'doc-1', 'title': '标题',
                'experiences': [{'docId': 'doc-1', 'title': '标题'}],
            })
            notifier = FakeNotifier()
            runtime = ExtractionRuntime(
                FakeHistory(), groups, processor, 'u1', notifier)
            task = runtime.start(
                ExtractRequest(groupId='g1', uploadBy='w00899061'), 0, 10)
            for _ in range(100):
                if not runtime.status(task_id=task['taskId'])['running']:
                    break
                time.sleep(0.01)
            self.assertEqual(
                [('w00899061', 'direct',
                  [{'docId': 'doc-1', 'title': '标题'}])], notifier.calls)
            runtime.close()


if __name__ == '__main__':
    unittest.main()
