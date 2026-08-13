import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from coreinsight_local_agent.extraction import ExtractionRuntime
from coreinsight_local_agent.models import ExtractRequest, GroupCreate
from coreinsight_local_agent.store import GroupStore


class FakeHistory:
    def fetch_page(self, group_id, start_ms, end_ms, cursor, limit):
        if not cursor:
            return {"items": [{"id": "3", "sender": "u", "content": "three", "timestamp": 3}, {"id": "2", "sender": "u", "content": "two", "timestamp": 2}], "nextCursor": "2", "hasMore": True, "totalHint": 0}
        return {"items": [{"id": "1", "sender": "u", "content": "one", "timestamp": 1}], "nextCursor": "", "hasMore": False, "totalHint": 0}


class ExtractionRuntimeTests(unittest.TestCase):
    def test_all_mode_excludes_message_ids_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = GroupStore(Path(directory)); groups.add(GroupCreate(groupId="g1", name="Group One"))
            runtime = ExtractionRuntime(FakeHistory(), groups, "https://example.test", "u1")
            calls = []
            def request(method, path, **kwargs):
                calls.append((method, path, kwargs.get("json")))
                return {"Success": True, "ChatId": "chat-1"} if path.endswith("/complete") else {"Success": True}
            payload = ExtractRequest(groupId="g1", extractMode="direct", selection={"mode": "all", "excludedMessageIds": ["2"]})
            with patch.object(runtime, "_request", side_effect=request):
                runtime.start(payload, 0, 10)
                for _ in range(100):
                    if not runtime.status()["running"]: break
                    time.sleep(0.01)
            chunks = [body for _, path, body in calls if "/chunks/" in path]
            self.assertEqual([["1", "3"]], [[item["id"] for item in chunk["messages"]] for chunk in chunks])
            complete = next(body for _, path, body in calls if path.endswith("/complete"))
            self.assertEqual({"chunkCount": 1, "messageCount": 2}, complete)
            self.assertEqual("processing", runtime.status()["status"])


if __name__ == "__main__":
    unittest.main()
