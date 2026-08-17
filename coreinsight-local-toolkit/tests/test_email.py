import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from coreinsight_local_toolkit.email_runtime import (
    EmailRuntime, EmailScheduleRuntime, _rule_match, _split_markdown)
from coreinsight_local_toolkit.email_store import EmailConfigStore
from coreinsight_local_toolkit.models import (
    EmailConfig, EmailExtractRequest, EmailRule, EmailScheduleSetRequest)
from coreinsight_local_toolkit.time_format import format_datetime


class FakeOutlook:
    def __init__(self):
        self.rows = [{
            "id": "mail-1", "subject": "GaussDB connection failure",
            "senderName": "Alice", "senderEmail": "alice@example.com",
            "receivedTime": "2026-08-17 10:00:00", "timestamp": 1786932000000,
            "conversationTopic": "database", "hasAttachments": True,
        }]

    def list_messages(self, folders, start_ms, end_ms, maximum=10000):
        return list(self.rows)

    def body_texts(self, item_ids):
        return {item_id: "timeout fixed by ssl configuration" for item_id in item_ids}

    def search_body_matches(self, folders, keyword_sets):
        return [{"mail-1"} if any(
            keyword.casefold() in "timeout fixed by ssl configuration"
            for keyword in keywords) else set() for keywords in keyword_sets]

    def get_message(self, item_id, process_attachments=True):
        return {**self.rows[0], "markdown": (
            "# GaussDB connection failure\n\n"
            "![certificate error](https://example.test/image.png)\n\nfixed")}


class FakeProcessor:
    def __init__(self):
        self.calls = []

    def validate(self, upload_by, skill_id, extract_mode):
        if not upload_by:
            raise ValueError("missing user")

    def process(self, messages, skill_id, upload_by, task_id, progress,
                cancel_event, **kwargs):
        self.calls.append((messages, skill_id, upload_by, kwargs))
        progress("skill", "running")
        return {"docId": "doc-1", "docIds": ["doc-1"],
                "title": "GaussDB SSL", "experiences": [
                    {"docId": "doc-1", "title": "GaussDB SSL"}]}


class EmailTests(unittest.TestCase):
    def test_rule_matching_and_long_markdown_split(self):
        row = {"subject": "Database timeout", "senderName": "Alice",
               "senderEmail": "alice@example.com"}
        rule = EmailRule(name="db", subjectKeywords=["database"],
                         bodyKeywords=["ssl"], logic="AND")
        self.assertTrue(_rule_match(row, rule, "SSL certificate"))
        chunks = _split_markdown("# title\n\n" + "x" * 80000)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 36000 for chunk in chunks))

    def test_store_assigns_rule_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EmailConfigStore(Path(directory))
            saved = store.save(EmailConfig(rules=[EmailRule(name="important")]))
            self.assertTrue(saved.rules[0].id)
            self.assertEqual(saved.rules[0].id, store.get().rules[0].id)

    def test_manual_extraction_uses_email_skill_and_notifies(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EmailConfigStore(Path(directory))
            store.save(EmailConfig(rules=[EmailRule(
                name="database", bodyKeywords=["ssl"])]))
            processor = FakeProcessor()
            notifier = type("Notifier", (), {"notify": lambda self, *args: True})()
            runtime = EmailRuntime(FakeOutlook(), store, processor, notifier)
            runtime.start(EmailExtractRequest(
                uploadBy="u1", selection={"mode": "explicit",
                                          "selectedItemIds": ["mail-1"]}), 0, 0)
            for _ in range(100):
                if not runtime.status()["running"]:
                    break
                time.sleep(.01)
            self.assertEqual("done", runtime.status()["status"])
            messages, skill_id, user, kwargs = processor.calls[0]
            self.assertEqual("email-experience-extractor", skill_id)
            self.assertEqual("u1", user)
            self.assertEqual("email", kwargs["source_type"])
            self.assertIn("![certificate error](https://example.test/image.png)",
                          messages[0]["rawContent"])

    def test_schedule_advances_cursor_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EmailConfigStore(Path(directory))
            processor = FakeProcessor()
            runtime = EmailRuntime(FakeOutlook(), store, processor)
            scheduler = EmailScheduleRuntime(store, runtime)
            now = datetime.now().astimezone()
            scheduler.set(EmailScheduleSetRequest(
                uploadBy="u1", scheduleTime=(now + timedelta(minutes=1)).strftime("%H:%M:%S"),
                since=format_datetime(now - timedelta(days=1))), now)
            before = store.get().scheduleCursor
            scheduler._completed(False, int(now.timestamp() * 1000))
            self.assertEqual(before, store.get().scheduleCursor)
            scheduler._completed(True, int(now.timestamp() * 1000))
            self.assertEqual(format_datetime(now), store.get().scheduleCursor)
            scheduler.close()


if __name__ == "__main__":
    unittest.main()
