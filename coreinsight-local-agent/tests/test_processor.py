import tempfile
import threading
import unittest
from pathlib import Path

from coreinsight_local_agent.config import Settings
from coreinsight_local_agent.processor import ExtractionCancelled, LocalExperienceProcessor


class ProcessorTests(unittest.TestCase):
    def processor(self, chunk_chars=40):
        return LocalExperienceProcessor(Settings(
            data_dir=Path(tempfile.gettempdir()), llm_chunk_chars=chunk_chars))

    def test_split_keeps_message_boundaries_when_possible(self):
        processor = self.processor(40)
        markdown = "### A\n\n" + "a" * 20 + "\n### B\n\n" + "b" * 20
        chunks = processor._split_markdown(markdown)
        self.assertEqual(markdown, "".join(chunks))
        self.assertEqual(2, len(chunks))

    def test_cancel_is_checked_before_processing(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(ExtractionCancelled):
            self.processor().process([], "", "u1", "task", cancel_event=event)


if __name__ == "__main__":
    unittest.main()
