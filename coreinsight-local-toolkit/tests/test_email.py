import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.email_runtime import (
    EmailRuntime, EmailScheduleRuntime, _rule_match, _split_markdown)
from coreinsight_local_toolkit.email_store import EmailConfigStore
from coreinsight_local_toolkit.models import (
    EmailConfig, EmailExtractRequest, EmailListRequest, EmailRule,
    EmailScheduleSetRequest)
from coreinsight_local_toolkit.outlook import (
    TABLE_COLUMNS, OutlookClient, _table_array_rows)
from coreinsight_local_toolkit.time_format import format_datetime


class FakeOutlook:
    def __init__(self):
        self.maximums = []
        self.folder_requests = []
        self.rows = [{
            "id": "mail-1", "subject": "GaussDB connection failure",
            "senderName": "Alice", "senderEmail": "alice@example.com",
            "receivedTime": "2026-08-17 10:00:00", "timestamp": 1786932000000,
            "conversationTopic": "database", "hasAttachments": True,
        }]

    def list_messages(self, folders, start_ms, end_ms, maximum=10000,
                      progress=None, cancelled=None):
        self.maximums.append(maximum)
        self.folder_requests.append(list(folders))
        rows = list(self.rows if maximum <= 0 else self.rows[:maximum])
        if progress:
            progress(len(rows), len(rows))
        return rows

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
    def test_outlook_probe_is_a_fast_compatibility_status_without_mapi(self):
        with tempfile.TemporaryDirectory() as directory:
            client = OutlookClient(Settings(data_dir=Path(directory)))
            with patch("coreinsight_local_toolkit.outlook.outlook_session",
                       side_effect=AssertionError("status must not open MAPI")):
                started = time.monotonic()
                current = client.probe()
                elapsed = time.monotonic() - started

            self.assertLess(elapsed, .1)
            self.assertTrue(current["ready"])
            self.assertFalse(current["checking"])
            self.assertEqual("LocalToolkit 已就绪", current["message"])
            with client.lock:
                self.assertTrue(client.probe()["busy"])

    def test_attachment_network_work_runs_outside_outlook_lock(self):
        class PropertyAccessor:
            @staticmethod
            def GetProperty(_name):
                return "image-1"

        class Attachment:
            FileName = "evidence.png"

            @staticmethod
            def SaveAsFile(path):
                Path(path).write_bytes(b"image")

        Attachment.PropertyAccessor = PropertyAccessor()

        class Attachments:
            Count = 1

            def __iter__(self):
                return iter([Attachment()])

        class Item:
            EntryID = "mail-1"
            Subject = "Failure"
            SenderName = "Alice"
            SenderEmailAddress = "alice@example.com"
            SenderEmailType = "SMTP"
            ReceivedTime = datetime.now().astimezone()
            ConversationTopic = "Failure"
            HTMLBody = '<p>Evidence</p><img src="cid:image-1">'
            Body = "Evidence"

        Item.Attachments = Attachments()

        class Namespace:
            @staticmethod
            def GetItemFromID(_item_id):
                return Item()

        @contextmanager
        def fake_session():
            yield Namespace()

        with tempfile.TemporaryDirectory() as directory:
            client = OutlookClient(Settings(data_dir=Path(directory)))
            lock_states = []

            def upload(_filename, _content):
                lock_states.append(client.lock.locked())
                return "https://example.test/evidence.png"

            def ocr(_filename, _content):
                lock_states.append(client.lock.locked())
                return "截图内容"

            client._upload = upload
            client._ocr = ocr
            with patch("coreinsight_local_toolkit.outlook.outlook_session",
                       fake_session):
                message = client.get_message("mail-1")

            self.assertEqual([False, False], lock_states)
            self.assertIn("https://example.test/evidence.png", message["htmlBody"])
            self.assertEqual("截图内容", message["attachments"][0]["ocr"])

    def test_outlook_table_reads_summaries_in_batches(self):
        class Columns:
            def __init__(self):
                self.names = []

            def RemoveAll(self):
                self.names.clear()

            def Add(self, name):
                self.names.append(name)

        now = datetime.now().astimezone()
        values = [
            (f"mail-{index}", f"Subject {index}", "Alice",
             "alice@example.com", now - timedelta(minutes=index),
             "Topic", False, "IPM.Note")
            for index in range(201)
        ]

        class Table:
            def __init__(self):
                self.Columns = Columns()
                self.position = 0
                self.batch_sizes = []

            @property
            def EndOfTable(self):
                return self.position >= len(values)

            def Sort(self, *_args):
                pass

            def GetRowCount(self):
                return len(values)

            def GetArray(self, maximum):
                self.batch_sizes.append(maximum)
                rows = values[self.position:self.position + maximum]
                self.position += len(rows)
                return rows

        table = Table()

        class Folder:
            FolderPath = "\\Mailbox\\Inbox"

            @staticmethod
            def GetTable():
                return table

        class Namespace:
            @staticmethod
            def GetDefaultFolder(_kind):
                return Folder()

        @contextmanager
        def fake_session():
            yield Namespace()

        with tempfile.TemporaryDirectory() as directory:
            client = OutlookClient(Settings(data_dir=Path(directory)))
            progress = []
            with patch("coreinsight_local_toolkit.outlook.outlook_session",
                       fake_session):
                rows = client.list_messages(
                    [], maximum=0,
                    progress=lambda scanned, total: progress.append(
                        (scanned, total)))

        self.assertEqual(201, len(rows))
        self.assertEqual(list(TABLE_COLUMNS), table.Columns.names)
        self.assertEqual([200, 200], table.batch_sizes)
        self.assertEqual((201, 201), progress[-1])

    def test_column_major_table_array_is_normalized(self):
        now = datetime.now().astimezone()
        rows = [
            ["mail-1", "Subject", "Alice", "alice@example.com", now,
             "Topic", False, "IPM.Note"],
            ["mail-2", "Subject 2", "Bob", "bob@example.com", now,
             "Topic 2", True, "IPM.Note"],
        ]
        columns = list(zip(*rows))

        self.assertEqual(rows, _table_array_rows(columns))

    def test_list_task_merges_selected_folders_for_frontend_paging(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EmailConfigStore(Path(directory))
            outlook = FakeOutlook()
            outlook.rows = [{
                "id": f"mail-{index}", "subject": f"Subject {index}",
                "senderName": "Alice", "senderEmail": "alice@example.com",
                "receivedTime": "2026-08-17 10:00:00",
                "timestamp": 200 - index, "conversationTopic": "topic",
                "hasAttachments": False,
            } for index in range(200)]
            runtime = EmailRuntime(outlook, store, FakeProcessor())

            started = runtime.start_list(
                EmailListRequest(folders=[
                    "Mailbox\\Inbox", "Mailbox\\Project"]), 0, 0)
            for _ in range(100):
                current = runtime.list_status(started["taskId"])
                if current and not current["running"]:
                    break
                time.sleep(.01)

            self.assertEqual("done", current["status"])
            self.assertEqual(200, len(current["items"]))
            self.assertEqual([0], outlook.maximums)
            self.assertEqual([[
                "Mailbox\\Inbox", "Mailbox\\Project"]],
                outlook.folder_requests)
            self.assertEqual(200, current["total"])
            self.assertEqual(
                ["Mailbox\\Inbox", "Mailbox\\Project"],
                current["folders"])

    def test_list_status_rejects_an_unknown_task(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EmailConfigStore(Path(directory))
            runtime = EmailRuntime(FakeOutlook(), store, FakeProcessor())

            self.assertIsNone(runtime.list_status("missing"))

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
                uploadBy="u1", scene="邮件问题定位经验", scene_id="251",
                selection={"mode": "explicit",
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
            self.assertEqual("邮件问题定位经验", kwargs["scene"])
            self.assertEqual("251", kwargs["scene_id"])
            self.assertIn("![certificate error](https://example.test/image.png)",
                          messages[0]["rawContent"])

    def test_schedule_advances_cursor_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EmailConfigStore(Path(directory))
            store.save(EmailConfig(rules=[EmailRule(
                name="technical", subjectKeywords=["failure"])]))
            processor = FakeProcessor()
            runtime = EmailRuntime(FakeOutlook(), store, processor)
            scheduler = EmailScheduleRuntime(store, runtime)
            now = datetime.now().astimezone()
            scheduler.set(EmailScheduleSetRequest(
                uploadBy="u1", scheduleTime=(now + timedelta(minutes=1)).strftime("%H:%M:%S"),
                since=format_datetime(now - timedelta(days=1)),
                scene="邮件问题定位经验", scene_id="251"), now)
            self.assertEqual("邮件问题定位经验", store.get().scene)
            self.assertEqual("251", store.get().scene_id)
            before = store.get().scheduleCursor
            scheduler._completed(False, int(now.timestamp() * 1000))
            self.assertEqual(before, store.get().scheduleCursor)
            scheduler._completed(True, int(now.timestamp() * 1000))
            self.assertEqual(format_datetime(now), store.get().scheduleCursor)
            scheduler.close()

    def test_schedule_requires_an_active_filter_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EmailConfigStore(Path(directory))
            processor = FakeProcessor()
            runtime = EmailRuntime(FakeOutlook(), store, processor)
            scheduler = EmailScheduleRuntime(store, runtime)
            with self.assertRaisesRegex(ValueError, "至少一条有效的提取规则"):
                scheduler.set(EmailScheduleSetRequest(
                    uploadBy="u1", since=format_datetime(
                        datetime.now().astimezone() - timedelta(days=1))))
            self.assertFalse(store.get().scheduleEnabled)
            scheduler.close()


if __name__ == "__main__":
    unittest.main()
