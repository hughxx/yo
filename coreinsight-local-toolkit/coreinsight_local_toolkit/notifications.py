from __future__ import annotations

import json
import logging
from urllib.parse import quote

import requests

from .config import Settings
from .environment import EnvironmentManager


logger = logging.getLogger(__name__)


class MessageNotifier:
    def __init__(self, settings: Settings, session=None):
        self.settings = settings
        self.session = session or requests
        self.environments = EnvironmentManager(settings.data_dir)

    def notify(self, user_id: str, extract_mode: str,
               experiences: list[dict], source_type: str = "welink") -> bool:
        user_id = str(user_id or '').strip()
        rows = [row for row in experiences if row.get('docId')]
        if not user_id or not rows or not self.settings.notification_url:
            return False
        success = True
        for offset in range(0, len(rows), 10):
            batch = rows[offset:offset + 10]
            source = "邮件" if source_type == "email" else "聊天记录"
            text = self._draft_text(batch, len(rows), offset, source) \
                if extract_mode == 'draft' \
                else self._direct_text(batch, len(rows), offset, source)
            try:
                response = self.session.post(
                    self.settings.notification_url,
                    files={
                        'target_accounts': (
                            None, json.dumps([user_id], ensure_ascii=False)),
                        'text': (None, text),
                    },
                    timeout=15)
                response.raise_for_status()
                logger.info(
                    'experience notification sent user_id=%s mode=%s count=%d',
                    user_id, extract_mode, len(batch))
            except Exception:
                success = False
                logger.exception(
                    'experience notification failed user_id=%s mode=%s',
                    user_id, extract_mode)
        return success

    def _draft_text(self, rows: list[dict], total: int, offset: int,
                    source: str) -> str:
        lines = [f'CoreInsight 已从{source}为您提取了 {total} 条待确认经验：']
        lines.extend(self._title_lines(rows, offset))
        lines.extend([
            '',
            '请前往“经验提取”页面，在右下角查看待确认经验：',
            self.environments.resolve_url(self.settings.experience_create_url),
        ])
        return '\n'.join(lines)

    def _direct_text(self, rows: list[dict], total: int, offset: int,
                     source: str) -> str:
        lines = [f'CoreInsight 已从{source}为您提取并入库 {total} 条经验：']
        portal = self.environments.resolve_url(
            self.settings.portal_url).rstrip('/')
        for index, row in enumerate(rows, offset + 1):
            title = str(row.get('title') or '未命名经验').strip()
            doc_id = quote(str(row['docId']), safe='')
            lines.extend([f'{index}. {title}', f'{portal}/experience/{doc_id}'])
        return '\n'.join(lines)

    @staticmethod
    def _title_lines(rows: list[dict], offset: int) -> list[str]:
        return [
            f'{index}. {str(row.get("title") or "未命名经验").strip()}'
            for index, row in enumerate(rows, offset + 1)
        ]
