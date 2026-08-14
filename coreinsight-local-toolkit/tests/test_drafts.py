import unittest
from pathlib import Path

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.drafts import DraftStore


class FakeCursor:
    def __init__(self, update_count=0):
        self.rowcount = 0
        self.update_count = update_count
        self.calls = []

    def execute(self, sql, values):
        self.calls.append((sql, values))
        if sql.startswith("UPDATE"):
            self.rowcount = self.update_count

    def close(self):
        pass


class FakeConnection:
    def __init__(self, update_count=0):
        self.cursor_value = FakeCursor(update_count)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class DraftStoreTests(unittest.TestCase):
    def settings(self):
        return Settings(
            data_dir=Path("D:/CoreInsight/LocalToolkit"),
            draft_db_user="db-user", draft_db_password="db-password")

    def test_new_draft_maps_fields_and_discards_rag(self):
        connection = FakeConnection(update_count=0)
        store = DraftStore(self.settings(), connect=lambda **kwargs: connection)
        doc_id = store.upsert({
            "title": "标题", "summary": "正文", "experience": "剧本",
            "rag_search_text": "不会写入", "scene_id": "251", "scene": "场景",
        }, "w00899061")
        self.assertEqual(32, len(doc_id))
        self.assertTrue(connection.committed)
        self.assertEqual(2, len(connection.cursor_value.calls))
        insert_sql, values = connection.cursor_value.calls[1]
        self.assertIn('INSERT INTO "coreinsight"."t_experience_draft"', insert_sql)
        self.assertEqual(doc_id, values[0])
        self.assertEqual("w00899061", values[1])
        self.assertEqual(("标题", "标题"), values[4:6])
        self.assertEqual(("正文", "剧本", "pending"), values[6:9])
        self.assertNotIn("不会写入", values)

    def test_existing_draft_is_partially_updated_and_reset_pending(self):
        connection = FakeConnection(update_count=1)
        store = DraftStore(self.settings(), connect=lambda **kwargs: connection)
        doc_id = store.upsert({"doc_id": "draft-1", "summary": "合并后的正文",
                               "rag_search_text": "丢弃"}, "w00899061")
        self.assertEqual("draft-1", doc_id)
        self.assertEqual(1, len(connection.cursor_value.calls))
        sql, values = connection.cursor_value.calls[0]
        self.assertIn('"llm_description" = %s', sql)
        self.assertNotIn("rag_search_text", sql)
        self.assertEqual(["合并后的正文", "pending", "draft-1", "w00899061"], values)

    def test_missing_existing_row_is_recreated_with_same_id(self):
        connection = FakeConnection(update_count=0)
        store = DraftStore(self.settings(), connect=lambda **kwargs: connection)
        self.assertEqual("draft-2", store.upsert(
            {"doc_id": "draft-2", "title": "再次提取"}, "w00899061"))
        self.assertEqual("draft-2", connection.cursor_value.calls[1][1][0])

    def test_credentials_are_required_without_opening_connection(self):
        called = []
        store = DraftStore(Settings(), connect=lambda **kwargs: called.append(kwargs))
        with self.assertRaisesRegex(ValueError, "COREINSIGHT_DRAFT_DB_USER"):
            store.upsert({"title": "x"}, "u1")
        self.assertEqual([], called)


if __name__ == "__main__":
    unittest.main()
