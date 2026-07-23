import unittest
from unittest.mock import patch

from modules.welink import history


def message(msg_id: int, timestamp: int):
    return {
        "msgId": msg_id,
        "serverSendTime": timestamp,
        "sender": "u001",
        "content": f"message-{msg_id}",
        "contentType": "TEXT_MSG",
    }


class WelinkHistoryTests(unittest.TestCase):
    def test_history_uses_min_message_id_to_page_older(self):
        first = [message(value, value * 1000) for value in range(200, 100, -1)]
        second = [message(101, 101000), message(100, 100000), message(99, 99000)]
        with patch.object(history, "query_page", side_effect=[
            {"items": first, "minMsgId": "101", "maxMsgId": "200", "total": 103},
            {"items": second, "minMsgId": "99", "maxMsgId": "101", "total": 103},
        ]) as query:
            items = history.fetch_history(
                {"type": "group", "source_id": "g1", "source_name": "群一"}
            )
        self.assertEqual(102, len(items))
        self.assertEqual("99", items[0]["id"])
        self.assertEqual("200", items[-1]["id"])
        self.assertEqual("101", query.call_args_list[1].args[1])
        self.assertTrue(query.call_args_list[1].kwargs["older"])

    def test_history_stops_after_crossing_start_time(self):
        page = [message(value, value * 1000) for value in range(200, 100, -1)]
        with patch.object(history, "query_page", return_value={
            "items": page, "minMsgId": "101", "maxMsgId": "200", "total": 500
        }) as query:
            items = history.fetch_history(
                {"type": "user", "source_id": "u1", "source_name": "用户一"},
                start_ms=150000,
                end_ms=180000,
            )
        self.assertEqual([str(value) for value in range(150, 181)], [x["id"] for x in items])
        query.assert_called_once()

    def test_source_key_keeps_group_and_user_independent(self):
        self.assertEqual("group:1", history.source_key({"type": "group", "source_id": "1"}))
        self.assertEqual("user:1", history.source_key({"type": "user", "source_id": "1"}))


if __name__ == "__main__":
    unittest.main()
