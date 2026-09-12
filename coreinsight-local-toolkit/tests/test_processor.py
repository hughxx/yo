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


RESULT["operation"] = "create"


class FakeResources:
    def __init__(self, output=None):
        self.output = output or json.dumps(RESULT, ensure_ascii=False)
        self.calls = []

    def validate(self, resource):
        self.validated = resource

    def generate(self, resource, prompt, workspace, cancel_event=None, progress=None):
        self.calls.append((resource, prompt, workspace))
        return self.output


class ProcessorTests(unittest.TestCase):
    def processor(self):
        data_directory = tempfile.TemporaryDirectory()
        self.addCleanup(data_directory.cleanup)
        processor = LocalExperienceProcessor(Settings(
            data_dir=Path(data_directory.name), experience_engine_url="http://engine",
            clouddrive_account="account", clouddrive_password="password"))
        processor.resources = FakeResources()
        return processor

    def test_local_workspace_model_flow(self):
        processor = self.processor()
        processor.instructions.prompt_path.write_text(
            "用户修改后的 Prompt", encoding="utf-8")
        processor.settings = processor.settings.__class__(
            **{**processor.settings.__dict__, "ocr_url": "http://ocr"})
        with patch.object(processor, "_push_experience", return_value="server-doc-1") as push:
            result = processor.process(
                [{"id": "1", "sender": "u", "timestamp": 1, "content": "hello"}],
                "u1", "task-1")
        inputs = list((Path(result["workspacePath"]) / "input").glob("*.md"))
        self.assertEqual(1, len(inputs))
        self.assertIn("hello", inputs[0].read_text(encoding="utf-8"))
        self.assertEqual("prompt", result["resource"])
        self.assertIn("用户修改后的 Prompt", processor.resources.calls[0][1])
        self.assertEqual("server-doc-1", result["docId"])
        push.assert_called_once()
        self.assertTrue((Path(result["workspacePath"]) / "output" /
                         "experiences.jsonl").exists())
        self.assertEqual(json.dumps(RESULT, ensure_ascii=False),
                         Path(result["modelResponsePath"]).read_text(encoding="utf-8"))

    def test_skill_flow_injects_exact_local_skill_and_reads_inputs_by_path(self):
        processor = self.processor()
        processor.instructions.skill_path.write_text(
            "# 用户修改后的 Skill", encoding="utf-8")
        with patch.object(processor, "_push_experience", return_value="doc-1"):
            result = processor.process(
                [{"id": "1", "sender": "u", "timestamp": 1,
                  "content": "very long source marker"}],
                "u1", "task-skill", resource="skill")
        resource, prompt, workspace = processor.resources.calls[0]
        self.assertEqual("skill", resource)
        self.assertIn(str(processor.instructions.skill_path), prompt)
        self.assertIn("SHA-256", prompt)
        self.assertIn("input/", prompt)
        self.assertNotIn("very long source marker", prompt)
        self.assertEqual(Path(result["workspacePath"]), workspace)

    def test_email_request_scene_overrides_model_scene(self):
        processor = self.processor()
        processor.resources.output = json.dumps({
            **RESULT, "scene": "模型场景", "scene_id": "999",
        }, ensure_ascii=False)
        with patch.object(processor, "validate"), patch.object(
                processor, "_push_experience", return_value="doc-1") as push:
            processor.process(
                [{"id": "1", "sender": "u", "timestamp": 1,
                  "content": "hello"}],
                "u1", "task-1",
                source_type="email", scene="邮件问题定位经验",
                scene_id="251")

        record = push.call_args.args[0]
        self.assertEqual("邮件问题定位经验", record["scene"])
        self.assertEqual("251", record["scene_id"])

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

    def test_workspace_uses_safe_group_directory(self):
        processor = self.processor()
        destination = processor._workspace_path(
            "../group:1", "welink-manual-task", "welink")
        self.assertEqual("group_1", destination.parent.name)
        self.assertTrue(destination.is_relative_to(
            processor.settings.data_dir / "extraction"))

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

    def test_draft_mode_routes_to_draft_store(self):
        processor = self.processor()
        processor.drafts = Mock()
        processor.drafts.save.return_value = "draft-1"
        self.assertEqual("draft-1", processor._push_experience(
            RESULT, "u1", "draft"))
        processor.drafts.save.assert_called_once_with(RESULT, "u1")

    def test_result_parser_accepts_pretty_json_jsonl_and_array(self):
        processor = self.processor()
        pretty = json.dumps(RESULT, ensure_ascii=False, indent=2)
        records, lines = processor._read_results(pretty)
        self.assertEqual([RESULT], records)
        self.assertEqual(1, len(lines))
        self.assertEqual(RESULT, json.loads(lines[0]))

        updated = {"operation": "update", "doc_id": "123", "summary": "补充内容"}
        raw = (json.dumps(RESULT, ensure_ascii=False) + "\n" +
               json.dumps(updated, ensure_ascii=False, indent=2))
        records, _ = processor._read_results(raw)
        self.assertEqual([RESULT, updated], records)

        records, _ = processor._read_results(json.dumps(
            [RESULT, updated], ensure_ascii=False, indent=2))
        self.assertEqual([RESULT, updated], records)

    def test_result_parser_repairs_common_model_json_mistakes(self):
        processor = self.processor()
        malformed_quotes = (
            '{"operation":"create","title":"引号问题",'
            '"summary":"正文包含 "quoted value" 文本",'
            '"experience":"第一行\n第二行",'
            '"rag_search_text":"json repair",}')
        raw = json.dumps(RESULT, ensure_ascii=False) + "\n" + malformed_quotes
        records, normalized = processor._read_results(raw)
        self.assertEqual(2, len(records))
        self.assertEqual('正文包含 "quoted value" 文本', records[1]["summary"])
        self.assertEqual("第一行\n第二行", records[1]["experience"])
        self.assertEqual(records[1], json.loads(normalized[1]))

        missing_comma = (
            '{"operation":"create" "title":"标题","summary":"摘要",'
            '"experience":"正文","rag_search_text":"关键词"}')
        values = processor._decode_json_values(missing_comma)
        self.assertEqual("标题", values[0]["title"])

    def test_result_parser_rejects_unrecoverable_json(self):
        processor = self.processor()
        with self.assertRaisesRegex(RuntimeError, "自动修复失败"):
            processor._decode_json_values('{"operation":"create"')

    def test_scheduled_workspace_is_stable_and_keeps_local_files(self):
        processor = self.processor()
        with patch.object(processor, "_push_experience", return_value="doc-1"):
            result = processor.process(
                [{"id": "1", "sender": "u", "timestamp": 1, "content": "hello"}],
                "u1", "task-1", group_id="g1", scheduled=True)
        expected = processor._workspace_id(
            "another-task", "g1", "u1", True, "direct")
        self.assertEqual(expected, result["workspaceId"])
        self.assertEqual(1, len(list(
            (Path(result["workspacePath"]) / "input").glob("*.md"))))

    def test_scheduled_workspaces_are_isolated_by_extract_mode(self):
        direct = LocalExperienceProcessor._workspace_id(
            "task", "g1", "u1", True, "direct")
        draft = LocalExperienceProcessor._workspace_id(
            "task", "g1", "u1", True, "draft")
        self.assertNotEqual(direct, draft)

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
            self.processor().process([], "u1", "task", cancel_event=event)

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
