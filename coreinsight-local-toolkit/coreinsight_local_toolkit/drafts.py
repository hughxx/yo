from __future__ import annotations

import logging
import re
import uuid

from .config import Settings


logger = logging.getLogger(__name__)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DraftStore:
    """Write Skill results to the platform's GaussDB draft table."""

    def __init__(self, settings: Settings, connect=None):
        self.settings = settings
        self._connect = connect

    def validate(self) -> None:
        missing = []
        for name, value in (
            ("COREINSIGHT_DRAFT_DB_HOST", self.settings.draft_db_host),
            ("COREINSIGHT_DRAFT_DB_NAME", self.settings.draft_db_name),
            ("COREINSIGHT_DRAFT_DB_USER", self.settings.draft_db_user),
            ("COREINSIGHT_DRAFT_DB_PASSWORD", self.settings.draft_db_password),
        ):
            if not value:
                missing.append(name)
        if missing:
            raise ValueError("缺少草稿数据库配置：" + ", ".join(missing))
        if not _IDENTIFIER.fullmatch(self.settings.draft_db_schema):
            raise ValueError("COREINSIGHT_DRAFT_DB_SCHEMA 不是合法标识符")

    def upsert(self, result: dict, user_id: str) -> str:
        self.validate()
        doc_id = str(result.get("doc_id") or "").strip() or uuid.uuid4().hex
        connect = self._connect
        if connect is None:
            import psycopg2
            connect = psycopg2.connect
        connection = connect(
            host=self.settings.draft_db_host, port=self.settings.draft_db_port,
            dbname=self.settings.draft_db_name, user=self.settings.draft_db_user,
            password=self.settings.draft_db_password, connect_timeout=10)
        updated = False
        try:
            cursor = connection.cursor()
            try:
                updated = self._update(cursor, doc_id, user_id, result)
                if not updated:
                    self._insert(cursor, doc_id, user_id, result)
                connection.commit()
            finally:
                cursor.close()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        logger.info("draft saved doc_id=%s operation=%s title=%s", doc_id,
                    "update" if updated else "create", str(result.get("title") or ""))
        return doc_id

    @property
    def _table(self) -> str:
        return f'"{self.settings.draft_db_schema}"."t_experience_draft"'

    def _update(self, cursor, doc_id: str, user_id: str, result: dict) -> bool:
        assignments, values = [], []
        for source, column in (
            ("scene", "scene"), ("scene_id", "scene_id"),
            ("title", "title"), ("title", "llm_title"),
            ("summary", "llm_description"), ("experience", "llm_content"),
        ):
            if source in result:
                assignments.append(f'"{column}" = %s')
                values.append(result[source])
        assignments.extend(['"status" = %s', '"updated_at" = CURRENT_TIMESTAMP'])
        values.extend(["pending", doc_id, user_id])
        cursor.execute(
            f'UPDATE {self._table} SET {", ".join(assignments)} '
            'WHERE "id" = %s AND "user_id" = %s', values)
        return cursor.rowcount > 0

    def _insert(self, cursor, doc_id: str, user_id: str, result: dict) -> None:
        title = result.get("title")
        cursor.execute(
            f'''INSERT INTO {self._table}
                ("id", "user_id", "scene", "scene_id", "title", "llm_title",
                 "llm_description", "llm_content", "status", "created_at", "updated_at")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
            (doc_id, user_id, result.get("scene") or "WeLink问题定位经验",
             str(result.get("scene_id") or "251"), title, title,
             result.get("summary"), result.get("experience"), "pending"))
