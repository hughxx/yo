import unittest
from unittest.mock import patch

from coreinsight_local_agent.welink import WelinkHistory


def message(message_id: int, timestamp: int):
    return {
        "msgId": message_id,
        "serverSendTime": timestamp,
        "sender": "u001",
        "content": f"message-{message_id}",
        "contentType": "TEXT_MSG",
    }


class WelinkHistoryTests(unittest.TestCase):
    def test_pages_backwards_and_filters_range(self):
        first = [message(value, value * 1000) for value in range(200, 100, -1)]
        second = [message(101, 101000), message(100, 100000), message(99, 99000)]
        history = WelinkHistory()
        with patch.object(history, "query_page", side_effect=[
            {"items": first, "minMsgId": "101", "total": 103},
            {"items": second, "minMsgId": "99", "total": 103},
        ]) as query:
            items = history.fetch("g1", start_ms=100000, end_ms=102000)
        self.assertEqual(["100", "101", "102"], [item["id"] for item in items])
        self.assertEqual("101", query.call_args_list[1].args[1])

    def test_normalizes_preview_shape(self):
        item = WelinkHistory.normalize(message(1, 1000))
        self.assertEqual("1", item["id"])
        self.assertTrue(item["checked"])
        self.assertEqual("message-1", item["content"])


if __name__ == "__main__":
    unittest.main()
