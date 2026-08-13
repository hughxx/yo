import json
import unittest
from unittest.mock import Mock, patch

from coreinsight_local_toolkit.remote import HermesClient, WorkspaceClient


class RemoteClientsTests(unittest.TestCase):
    def test_workspace_writes_utf8_text(self):
        response = Mock(content=b'{}')
        response.json.return_value = {"ok": True}
        client = WorkspaceClient("http://files")
        client.session.request = Mock(return_value=response)
        client.write_text("w1", "input/chat.md", "中文")
        request = client.session.request
        _, url = request.call_args.args
        self.assertEqual("http://files/api/workspaces/w1/file", url)
        self.assertEqual({"path": "input/chat.md", "content": "中文"},
                         request.call_args.kwargs["json"])
        response.raise_for_status.assert_called_once()

    def test_hermes_submit_uses_workspace_skill(self):
        response = Mock(content=b'{}')
        response.json.return_value = {"run_id": "run-1"}
        client = HermesClient("http://hermes", "key")
        client.session.request = Mock(return_value=response)
        run_id = client.submit(
            "workspace-1", "session-1", "welink-experience-extractor")
        request = client.session.request
        self.assertEqual("run-1", run_id)
        body = request.call_args.kwargs["json"]
        self.assertIn("Skill", body["input"])
        self.assertIn("/workspace/workspace-1/skills/welink-experience-extractor/SKILL.md",
                      body["instructions"])
        self.assertEqual("Bearer key", request.call_args.kwargs["headers"]["Authorization"])

    @patch.object(HermesClient, "final_answer", return_value=json.dumps({"title": "t"}))
    def test_hermes_waits_for_completed_event(self, final_answer):
        response = Mock()
        response.iter_lines.return_value = [
            b"event: run.completed",
            b'data: {"event":"run.completed","run_id":"run-1"}',
        ]
        client = HermesClient("http://hermes", "key")
        client.session.get = Mock(return_value=response)
        result = client.wait("run-1")
        self.assertIn("title", result)
        final_answer.assert_called_once_with("run-1")
        response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
