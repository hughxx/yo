import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from coreinsight_local_toolkit.models import GroupCreate, ScheduleSetRequest
from coreinsight_local_toolkit.scheduler import ScheduleRuntime, next_cron, next_run
from coreinsight_local_toolkit.store import GroupStore


class FakeProcessor:
    def validate(self, upload_by, skill_id=None, extract_mode="direct"):
        if not upload_by:
            raise ValueError("missing uploader")


class FakeExtraction:
    def __init__(self):
        self.processor = FakeProcessor()
        self.default_upload_by = "u1"
        self.calls = []

    def status(self):
        return {"running": False}

    def start(self, payload, start_ms, end_ms, scheduled=False, on_complete=None):
        self.calls.append((payload, start_ms, end_ms, scheduled))
        on_complete(True, end_ms, {})


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = GroupStore(Path(self.temporary.name))
        self.store.add(GroupCreate(groupId="g1"))
        self.extraction = FakeExtraction()
        self.runtime = ScheduleRuntime(self.store, self.extraction)

    def tearDown(self):
        self.runtime.close()
        self.temporary.cleanup()

    def test_daily_schedule_runs_incrementally_and_advances_after_success(self):
        now = datetime.fromisoformat("2026-08-13T08:00:00+08:00")
        saved = self.runtime.set(ScheduleSetRequest(
            groupId="g1", uploadBy="u1", scheduleFreq="daily",
            scheduleTime="09:00:00"), now)
        self.assertEqual("2026-08-13 09:00:00", saved.scheduleNextRun)

        due = datetime.fromisoformat("2026-08-13T09:00:01+08:00")
        self.assertTrue(self.runtime.tick(due))
        call = self.extraction.calls[0]
        self.assertEqual(int(now.timestamp() * 1000), call[1])
        self.assertEqual(int(due.timestamp() * 1000), call[2])
        self.assertTrue(call[3])
        group = self.store.get("g1")
        self.assertEqual("2026-08-13 09:00:01", group.scheduleLastRun)
        self.assertEqual("scheduled", group.status)

    def test_custom_cron(self):
        value = next_cron("*/15 9 * * 1-5", datetime.fromisoformat("2026-08-13T09:07:00+08:00"))
        self.assertEqual("2026-08-13T09:15:00+08:00", value.isoformat())

    def test_draft_schedule_keeps_draft_mode(self):
        now = datetime.fromisoformat("2026-08-13T08:00:00+08:00")
        self.runtime.set(ScheduleSetRequest(
            groupId="g1", uploadBy="u1", extractMode="draft",
            scheduleFreq="daily", scheduleTime="09:00:00"), now)
        self.assertTrue(self.runtime.tick(
            datetime.fromisoformat("2026-08-13T09:00:01+08:00")))
        self.assertEqual("draft", self.extraction.calls[0][0].extractMode)

    def test_cron_uses_standard_or_rule_for_day_and_weekday(self):
        value = next_cron("0 9 15 * 1", datetime.fromisoformat("2026-08-13T10:00:00+08:00"))
        self.assertEqual("2026-08-15T09:00:00+08:00", value.isoformat())

    def test_weekly_schedule_uses_day_it_was_configured(self):
        group = self.store.get("g1")
        group.scheduleFreq = "weekly"
        group.scheduleTime = "09:00:00"
        group.scheduleWeekday = 3
        value = next_run(group, datetime.fromisoformat("2026-08-13T10:00:00+08:00"))
        self.assertEqual("2026-08-20T09:00:00+08:00", value.isoformat())


if __name__ == "__main__":
    unittest.main()
