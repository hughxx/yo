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
    def test_older_page_uses_direction_zero(self):
        history = WelinkHistory()
        with patch.object(history, "_run", return_value={
            "respData": {"chatInfo": [], "msgTotalCount": 0}
        }) as run:
            history.query_page("g1", "89325998832806069", count=2)
        args = run.call_args.args[0]
        self.assertEqual("0", args[args.index("--query-direction") + 1])
        self.assertEqual("89325998832806069", args[args.index("--message-id") + 1])

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

    def test_short_page_does_not_mean_end_of_history(self):
        history = WelinkHistory()
        with patch.object(history, "query_page", side_effect=[
            {"items": [message(10, 10000), message(9, 9000)],
             "minMsgId": "9", "total": 20},
            {"items": [message(9, 9000), message(8, 8000)],
             "minMsgId": "8", "total": 20},
            {"items": [], "minMsgId": "", "total": 20},
        ]) as query:
            items = history.fetch("g1")
        self.assertEqual(["8", "9", "10"], [item["id"] for item in items])
        self.assertEqual(3, query.call_count)

    def test_page_omits_repeated_cursor_row(self):
        history = WelinkHistory()
        with patch.object(history, "query_page", return_value={
            "items": [message(9, 9000), message(8, 8000)],
            "minMsgId": "8", "total": 20,
        }):
            page = history.fetch_page("g1", cursor="9")
        self.assertEqual(["8"], [item["id"] for item in page["items"]])
        self.assertTrue(page["hasMore"])
        self.assertEqual("8", page["nextCursor"])

    def test_normalizes_preview_shape(self):
        item = WelinkHistory.normalize(message(1, 1000))
        self.assertEqual("1", item["id"])
        self.assertTrue(item["checked"])
        self.assertEqual("message-1", item["content"])


if __name__ == "__main__":
    unittest.main()
