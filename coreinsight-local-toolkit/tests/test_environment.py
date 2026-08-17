import json
import tempfile
import unittest
from pathlib import Path

from coreinsight_local_toolkit.environment import (
    EnvironmentManager, PRODUCTION, TESTING,
)


class EnvironmentManagerTests(unittest.TestCase):
    def manager(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return EnvironmentManager(Path(directory.name))

    def test_defaults_from_known_host_and_persists_selection(self):
        manager = self.manager()
        self.assertEqual(PRODUCTION, manager.current(
            'https://coreinsight.rnd.huawei.com'))
        self.assertEqual(TESTING, manager.current(
            'https://coreinsight-beta.rnd.huawei.com'))
        manager.set(TESTING)
        self.assertEqual(TESTING, manager.current(
            'https://coreinsight.rnd.huawei.com'))
        self.assertEqual(
            {'environment': TESTING},
            json.loads(manager.path.read_text(encoding='utf-8')))

    def test_only_rewrites_the_two_coreinsight_hosts(self):
        manager = self.manager()
        manager.set(TESTING)
        self.assertEqual(
            'https://coreinsight-beta.rnd.huawei.com/chat/a?q=1#x',
            manager.resolve_url(
                'https://coreinsight.rnd.huawei.com/chat/a?q=1#x'))
        self.assertEqual(
            'https://fuyao.rnd.huawei.com/memory/experience/doc',
            manager.resolve_url(
                'https://fuyao.rnd.huawei.com/memory/experience/doc'))
        manager.set(PRODUCTION)
        self.assertEqual(
            'https://coreinsight.rnd.huawei.com/chat',
            manager.resolve_url(
                'https://coreinsight-beta.rnd.huawei.com/chat'))

    def test_invalid_environment_is_rejected(self):
        manager = self.manager()
        with self.assertRaisesRegex(ValueError, 'production'):
            manager.set('staging')


if __name__ == '__main__':
    unittest.main()
