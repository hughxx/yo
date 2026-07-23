from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime import EmailRuntime, EventStream, WelinkRuntime


SETTINGS = {
    "backendUrl": "https://example.invalid/api",
    "userId": "u1",
    "namespace": "ns",
    "customJsonConfig": "{}",
    "scanFolders": [],
    "outputDir": "D:/tmp/archive",
}


def mail(item_id):
    return {
        "item_id": item_id, "subject": item_id, "sender_name": "sender",
        "sender_email": "sender@example.com", "received_time": "2026-01-01T00:00:00",
        "conversation_topic": item_id, "html_body": "<p>body</p>", "markdown_body": "body",
    }


class RuntimeTests(unittest.TestCase):
    def wait_done(self, runtime, timeout=5):
        end = time.time() + timeout
        while runtime.status()["running"] and time.time() < end:
            time.sleep(0.01)
        self.assertFalse(runtime.status()["running"])

    def test_event_stream_cursor(self):
        stream = EventStream()
        stream.emit("email", "one")
        first = stream.read(0)
        stream.emit("email", "two")
        second = stream.read(first["cursor"])
        self.assertEqual([x["message"] for x in first["events"]], ["one"])
        self.assertEqual([x["message"] for x in second["events"]], ["two"])

    def test_email_batch_processes_all_items(self):
        runtime = EmailRuntime(EventStream())
        runtime._cache = [{**mail(str(i)), "matched_rule": "rule"} for i in range(12)]
        with patch("runtime.store.load_settings", return_value=dict(SETTINGS)), \
             patch("runtime.store.save_settings"), \
             patch("runtime.outlook.mail_get", side_effect=lambda item_id, _api: mail(item_id)), \
             patch("runtime.backend.receive_email") as receive, \
             patch("runtime.local_archive.save_email"):
            runtime.start([str(i) for i in range(12)], True, False, "处理选中")
            self.wait_done(runtime)
        status = runtime.status()
        self.assertEqual(status["success"], 12)
        self.assertEqual(status["failed"], 0)
        self.assertEqual(receive.call_count, 12)
        self.assertTrue(receive.call_args.args[0]["Force"])

    def test_email_task_can_cancel_between_messages(self):
        runtime = EmailRuntime(EventStream())
        runtime._cache = [{**mail(str(i)), "matched_rule": "rule"} for i in range(30)]

        def slow_get(item_id, _api):
            time.sleep(0.03)
            return mail(item_id)

        with patch("runtime.store.load_settings", return_value=dict(SETTINGS)), \
             patch("runtime.store.save_settings"), \
             patch("runtime.outlook.mail_get", side_effect=slow_get), \
             patch("runtime.backend.receive_email"), \
             patch("runtime.local_archive.save_email"):
            runtime.start([str(i) for i in range(30)], True, False, "处理选中")
            time.sleep(0.09)
            runtime.cancel()
            self.wait_done(runtime)
        status = runtime.status()
        self.assertTrue(status["cancelled"])
        self.assertLess(status["current"], 30)

    def test_manual_rule_preview_uses_outlook_match_maps(self):
        runtime = EmailRuntime(EventStream())
        runtime._cache = [mail("1"), mail("2")]
        maps = {"subj": {0: {"2"}}, "body": {}, "sender": {}}
        with patch("runtime.store.load_settings", return_value=dict(SETTINGS)), \
             patch("runtime.email_rules.build_match_maps", return_value=maps):
            matched = runtime.preview_rule({
                "keywords": ["告警"], "body_keywords": [], "senders": [], "logic": "OR"
            })
        self.assertEqual(matched, ["2"])

    def test_manual_rule_preview_requires_a_condition(self):
        runtime = EmailRuntime(EventStream())
        with patch("runtime.store.load_settings", return_value=dict(SETTINGS)):
            with self.assertRaisesRegex(ValueError, "至少填写一个匹配条件"):
                runtime.preview_rule({})

    def test_manual_rule_preview_matches_any_rule(self):
        runtime = EmailRuntime(EventStream())
        runtime._cache = [mail("1"), mail("2"), mail("3")]
        maps = {"subj": {0: {"1"}, 1: {"3"}}, "body": {}, "sender": {}}
        rules = [
            {"name": "告警", "keywords": ["告警"], "logic": "OR"},
            {"name": "反馈", "keywords": ["反馈"], "logic": "OR"},
        ]
        with patch("runtime.store.load_settings", return_value=dict(SETTINGS)), \
             patch("runtime.email_rules.build_match_maps", return_value=maps):
            matched = runtime.preview_rules(rules)
        self.assertEqual(matched, ["1", "3"])

    def test_welink_sources_are_processed_as_independent_jobs(self):
        runtime = WelinkRuntime(EventStream())
        runtime._cache = {
            "user:u1": [{"id": "1", "timestamp": 1000, "raw": {"msgId": 1}}],
            "user:u2": [{"id": "2", "timestamp": 2000, "raw": {"msgId": 2}}],
        }
        jobs = [
            {"source": {"type": "user", "source_id": "u1", "source_name": "用户一"},
             "messageIds": ["1"]},
            {"source": {"type": "user", "source_id": "u2", "source_name": "用户二"},
             "messageIds": ["2"]},
        ]
        with patch("runtime.store.load_settings", return_value=dict(SETTINGS)), \
             patch.object(runtime, "_process_source") as process:
            runtime.start(jobs)
            self.wait_done(runtime)
        self.assertEqual(2, process.call_count)
        self.assertEqual(["用户一", "用户二"],
                         [call.args[0]["source_name"] for call in process.call_args_list])


if __name__ == "__main__":
    unittest.main()
