import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from coreinsight_local_agent.config import Settings
from coreinsight_local_agent.processor import ExtractionCancelled, LocalExperienceProcessor


RESULT = {"title": "标题", "summary": "摘要", "experience": "## 方案\n内容",
          "rag_search_text": "关键词"}


class FakeWorkspaces:
    def __init__(self):
        self.files = {}
        self.deleted = []

    def create(self, workspace_id):
        self.workspace_id = workspace_id

    def write_text(self, workspace_id, path, content):
        self.files[path] = content

    def upload(self, workspace_id, path, filename, content):
        self.files[f"{path}/{filename}"] = content
        return f"{path}/{filename}"

    def read_text(self, workspace_id, path):
        return self.files[path]

    def delete(self, workspace_id):
        self.deleted.append(workspace_id)


class FakeHermes:
    def submit(self, workspace_id, session_id, skill_id):
        self.submitted = (workspace_id, session_id, skill_id)
        return "run-1"

    def wait(self, run_id, cancel_event=None, progress=None):
        return json.dumps(RESULT, ensure_ascii=False)

    def stop(self, run_id):
        pass


class ProcessorTests(unittest.TestCase):
    def processor(self):
        processor = LocalExperienceProcessor(Settings(
            data_dir=Path(tempfile.gettempdir()), experience_engine_url="http://engine"))
        processor.workspaces = FakeWorkspaces()
        processor.hermes = FakeHermes()
        return processor

    def test_skill_workspace_flow(self):
        processor = self.processor()
        processor.workspaces.files["output/experience.json"] = json.dumps(RESULT)
        with patch.object(processor, "_push_experience") as push:
            result = processor.process(
                [{"id": "1", "sender": "u", "timestamp": 1, "content": "hello"}],
                "welink-experience-extractor", "u1", "task-1")
        self.assertIn("input/chat.md", processor.workspaces.files)
        self.assertIn("skills/welink-experience-extractor/SKILL.md", processor.workspaces.files)
        self.assertEqual("welink-experience-extractor", result["skillId"])
        push.assert_called_once()
        self.assertEqual(1, len(processor.workspaces.deleted))

    def test_cancel_is_checked_before_workspace_creation(self):
        event = threading.Event(); event.set()
        with self.assertRaises(ExtractionCancelled):
            self.processor().process([], "welink-experience-extractor", "u1", "task", cancel_event=event)


if __name__ == "__main__":
    unittest.main()
