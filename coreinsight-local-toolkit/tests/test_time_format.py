import unittest

from coreinsight_local_toolkit.app import _to_timestamp
from coreinsight_local_toolkit.models import GroupConfig
from coreinsight_local_toolkit.time_format import normalize_datetime


class TimeFormatTests(unittest.TestCase):
    def test_normalizes_t_separator_and_fractional_seconds(self):
        self.assertEqual(
            "2026-01-23 00:00:00",
            normalize_datetime("2026-01-23T00:00:00.987654"))

    def test_group_datetime_fields_use_one_format(self):
        group = GroupConfig(
            groupId="g1", startTime="2026-01-23T00:00:00",
            endTime="2026-01-24 01:02:03.456",
            scheduleLastRun="2026-01-24T02:03:04",
            scheduleNextRun="2026-01-25 03:04:05")
        self.assertEqual("2026-01-23 00:00:00", group.startTime)
        self.assertEqual("2026-01-24 01:02:03", group.endTime)
        self.assertEqual("2026-01-24 02:03:04", group.scheduleLastRun)
        self.assertEqual("2026-01-25 03:04:05", group.scheduleNextRun)

    def test_timestamp_parser_accepts_year_before_1970(self):
        value = _to_timestamp("1111-11-11T00:00:00", "startTime")
        self.assertIsInstance(value, int)
        self.assertLess(value, 0)


if __name__ == "__main__":
    unittest.main()
