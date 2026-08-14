import logging
import os
import tempfile
import time
import unittest
from pathlib import Path

from coreinsight_local_toolkit.__main__ import cleanup_stale_runtime, configure_logging
from coreinsight_local_toolkit.config import Settings


class ConfigTests(unittest.TestCase):
    def test_default_origins_include_local_huawei_development_domain(self):
        settings = Settings()
        self.assertIn("http://localhost.huawei.com:8080", settings.allowed_origins)
        self.assertIn("https://localhost.huawei.com:8080", settings.allowed_origins)

    def test_default_data_dir_is_on_d_drive(self):
        self.assertEqual(Path("D:/CoreInsight/LocalToolkit"), Settings().data_dir)

    def test_logging_is_created_below_data_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            path = configure_logging(data_dir)
            self.assertEqual(data_dir / "logs" / "toolkit.log", path)
            self.assertTrue(path.exists())
            for handler in logging.getLogger().handlers[:]:
                logging.getLogger().removeHandler(handler)
                handler.close()

    def test_stale_runtime_directories_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            stale = data_dir / "runtime" / "_MEI-old"
            fresh = data_dir / "runtime" / "_MEI-fresh"
            stale.mkdir(parents=True)
            fresh.mkdir()
            old = time.time() - 90_000
            os.utime(stale, (old, old))
            self.assertEqual(1, cleanup_stale_runtime(data_dir))
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())


if __name__ == "__main__":
    unittest.main()
