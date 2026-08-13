import tempfile
import unittest
from pathlib import Path

from coreinsight_local_toolkit.models import GroupConfig, GroupCreate
from coreinsight_local_toolkit.store import GroupStore


class GroupStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = GroupStore(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def test_crud_and_defaults(self):
        created = self.store.add(GroupCreate(groupId=" group-1 ", name=" 群一 "))
        self.assertEqual("group-1", created.groupId)
        self.assertEqual("7d", created.quickRange)
        self.assertEqual("群一", created.name)

        created.quickRange = "today"
        self.store.update(created)
        self.assertEqual("today", self.store.get("group-1").quickRange)

        self.store.delete("group-1")
        self.assertEqual([], self.store.list())

    def test_extracting_is_reset_after_restart(self):
        self.store.add(GroupCreate(groupId="group-1", name=""))
        group = self.store.get("group-1")
        group.status = "extracting"
        self.store.update(group)
        self.assertEqual("idle", GroupStore(Path(self.temporary.name)).get("group-1").status)

    def test_scheduled_group_returns_to_scheduled_after_restart(self):
        self.store.add(GroupCreate(groupId="group-1", name=""))
        group = self.store.get("group-1")
        group.scheduleEnabled = True
        group.status = "extracting"
        self.store.update(group)
        self.assertEqual("scheduled", GroupStore(Path(self.temporary.name)).get("group-1").status)


if __name__ == "__main__":
    unittest.main()
