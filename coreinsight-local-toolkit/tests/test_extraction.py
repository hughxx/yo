import tempfile
import time
import unittest
from pathlib import Path

from coreinsight_local_toolkit.extraction import ExtractionRuntime
from coreinsight_local_toolkit.models import ExtractRequest, GroupCreate
from coreinsight_local_toolkit.store import GroupStore


class FakeHistory:
    def fetch_page(self, group_id, start_ms, end_ms, cursor, limit):
        if not cursor:
            return {'items': [{'id': '3'}, {'id': '2'}],
                    'nextCursor': '2', 'hasMore': True}
        return {'items': [{'id': '1'}], 'nextCursor': '', 'hasMore': False}


class FakeProcessor:
    def __init__(self):
        self.calls = []

    def validate(self, upload_by, skill_id=None, extract_mode="direct"):
        pass

    def process(self, *args, **kwargs):
        self.calls.append(args)
        return {'docId': 'doc-1', 'title': 'Test title'}


class ExtractionRuntimeTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
