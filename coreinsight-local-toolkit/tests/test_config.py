import logging
import tempfile
import unittest
from pathlib import Path

from coreinsight_local_toolkit.__main__ import configure_logging
from coreinsight_local_toolkit.config import Settings


class ConfigTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
