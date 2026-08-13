import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.processor import ExtractionCancelled, LocalExperienceProcessor


RESULT = {"title": "标题", "summary": "摘要", "experience": "## 方案\n内容",
          "rag_search_text": "关键词"}


class FakeWorkspaces:
    def __init__(self):
        self.files = {}
        self.deleted = []
        self.deleted_paths = []

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

    def delete_path(self, workspace_id, path):
        self.deleted_paths.append((workspace_id, path))
        self.files.pop(path, None)


class FakeHermes:
    def submit(self, workspace_id, session_id, skill_id, input_paths=None, scheduled=False):
        self.submitted = (workspace_id, session_id, skill_id, input_paths, scheduled)
        return "run-1"

    def wait(self, run_id, cancel_event=None, progress=None):
        return json.dumps(RESULT, ensure_ascii=False)

    def stop(self, run_id):
        pass


class ProcessorTests(unittest.TestCase):
    def processor(self):
        processor = LocalExperienceProcessor(Settings(
            data_dir=Path(tempfile.gettempdir()), experience_engine_url="http://engine",
            clouddrive_account="account", clouddrive_password="password"))
        processor.workspaces = FakeWorkspaces()
        processor.hermes = FakeHermes()
        return processor

    def test_skill_workspace_flow(self):
        processor = self.processor()
        processor.settings = processor.settings.__class__(
            **{**processor.settings.__dict__, "ocr_url": "http://ocr"})
        processor.workspaces.files["output/experiences.jsonl"] = json.dumps(RESULT)
        with patch.object(processor, "_push_experience", return_value="server-doc-1") as push:
            result = processor.process(
                [{"id": "1", "sender": "u", "timestamp": 1, "content": "hello"}],
                "welink-experience-extractor", "u1", "task-1")
        self.assertTrue(any(path.startswith("input/000001_")
                            for path in processor.workspaces.files))
        self.assertIn("skills/welink-experience-extractor/SKILL.md", processor.workspaces.files)
        self.assertEqual("welink-experience-extractor", result["skillId"])
        self.assertEqual("server-doc-1", result["docId"])
        push.assert_called_once()
        self.assertEqual(1, len(processor.workspaces.deleted))

    def test_chunks_split_only_between_messages(self):
        processor = self.processor()
        messages = [
            {"id": "1", "sender": "u", "timestamp": 1, "content": "a" * 39900},
            {"id": "2", "sender": "u", "timestamp": 2, "content": "b" * 200},
        ]
        chunks = processor._to_markdown_chunks(messages)
        self.assertEqual(2, len(chunks))
        self.assertIn("消息 ID：1", chunks[0]["content"])
        self.assertNotIn("消息 ID：2", chunks[0]["content"])
        self.assertIn("消息 ID：2", chunks[1]["content"])

    def test_create_and_update_use_engine_contract(self):
        processor = self.processor()
        create_response = Mock()
        create_response.raise_for_status.return_value = None
        create_response.json.return_value = {"code": 200, "data": {"doc_id": 123}}
        update_response = Mock()
        update_response.raise_for_status.return_value = None
        update_response.json.return_value = {"code": 200, "data": {"doc_id": 123}}
        with patch("coreinsight_local_toolkit.processor.requests.post",
                   return_value=create_response) as post, \
                patch("coreinsight_local_toolkit.processor.requests.put",
                      return_value=update_response) as put:
            self.assertEqual("123", processor._push_experience(RESULT, "u1"))
            self.assertEqual("123", processor._push_experience(
                {"doc_id": "123", "summary": "更新"}, "u1"))
        self.assertEqual("http://engine/memory/experience/doc", post.call_args.args[0])
        self.assertEqual("http://engine/memory/experience/doc/123", put.call_args.args[0])
        self.assertEqual({"user_id": "u1", "summary": "更新"}, put.call_args.kwargs["json"])

    def test_result_parser_accepts_pretty_json_jsonl_and_array(self):
        processor = self.processor()
        pretty = json.dumps(RESULT, ensure_ascii=False, indent=2)
        processor.workspaces.files["output/experiences.jsonl"] = pretty
        records, lines = processor._read_results("w1", "")
        self.assertEqual([RESULT], records)
        self.assertEqual(1, len(lines))
        self.assertEqual(RESULT, json.loads(lines[0]))

        updated = {"doc_id": "123", "summary": "补充内容"}
        processor.workspaces.files["output/experiences.jsonl"] = (
            json.dumps(RESULT, ensure_ascii=False) + "\n" +
            json.dumps(updated, ensure_ascii=False, indent=2))
        records, _ = processor._read_results("w1", "")
        self.assertEqual([RESULT, updated], records)

        processor.workspaces.files["output/experiences.jsonl"] = json.dumps(
            [RESULT, updated], ensure_ascii=False, indent=2)
        records, _ = processor._read_results("w1", "")
        self.assertEqual([RESULT, updated], records)

    def test_scheduled_workspace_is_stable_and_is_not_deleted(self):
        processor = self.processor()
        processor.workspaces.files["output/experiences.jsonl"] = ""
        with tempfile.TemporaryDirectory() as directory:
            processor._state_path = Path(directory) / "state.json"
            result = processor.process(
                [{"id": "1", "sender": "u", "timestamp": 1, "content": "hello"}],
                "welink-experience-extractor", "u1", "task-1",
                group_id="g1", scheduled=True)
        expected = processor._workspace_id(
            "another-task", "g1", "welink-experience-extractor", "u1", True)
        self.assertEqual(expected, result["workspaceId"])
        self.assertEqual([], processor.workspaces.deleted)
        self.assertEqual(1, len(processor.workspaces.deleted_paths))

    def test_compaction_keeps_latest_version_per_doc_id(self):
        records = [
            {"doc_id": "1", "summary": "old"},
            {"doc_id": "2", "summary": "only"},
            {"doc_id": "1", "summary": "new"},
        ]
        self.assertEqual(
            [{"doc_id": "2", "summary": "only"},
             {"doc_id": "1", "summary": "new"}],
            LocalExperienceProcessor._latest_experience_versions(records))

    def test_cancel_is_checked_before_workspace_creation(self):
        event = threading.Event(); event.set()
        with self.assertRaises(ExtractionCancelled):
            self.processor().process([], "welink-experience-extractor", "u1", "task", cancel_event=event)

    def test_image_becomes_public_markdown_link(self):
        processor = self.processor()
        content = "/:um_begin{download|File|123|问题 截图.png|0|1;2;code}/:um_end"
        upload_response = Mock(); upload_response.raise_for_status.return_value = None
        ocr_response = Mock(); ocr_response.raise_for_status.return_value = None
        ocr_response.json.return_value = {"result": "错误码 500\n连接失败"}
        with patch.object(processor, "_download", return_value=b"image"), \
                patch("coreinsight_local_toolkit.processor.requests.post",
                      side_effect=[upload_response, ocr_response]):
            markdown = processor._to_markdown([
                {"id": "1", "sender": "u", "timestamp": 1, "rawContent": content}])
        self.assertIn("![错误码 500 连接失败](https://fuyao-data-server.rnd.huawei.com/rag_pic/", markdown)
        self.assertIn("%20", markdown)
        self.assertNotIn("/workspace/", markdown)


if __name__ == "__main__":
    unittest.main()
