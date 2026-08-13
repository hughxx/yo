import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.service import welink_import_service as imports


class WelinkImportServiceTests(unittest.TestCase):
    def test_chunk_round_trip_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(imports, "_ROOT", Path(directory)):
            imports.create_import("batch-1", {"groupId": "g1"})
            messages = [{"id": "2", "timestamp": 2}, {"id": "1", "timestamp": 1}]
            first = imports.save_chunk("batch-1", 0, messages); second = imports.save_chunk("batch-1", 0, messages)
            self.assertEqual(first["sha256"], second["sha256"])
            meta, loaded = imports.load_complete("batch-1", 1, 2)
            self.assertEqual("g1", meta["groupId"])
            self.assertEqual(["1", "2"], [item["id"] for item in loaded])


if __name__ == "__main__":
    unittest.main()
