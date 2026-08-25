from __future__ import annotations

import logging
import uuid
from urllib.parse import quote

import requests

from .config import Settings
from .environment import EnvironmentManager


logger = logging.getLogger(__name__)


class DraftClient:
    def __init__(self, settings: Settings, session=None):
        self.settings = settings
        self.session = session or requests
        self.environments = EnvironmentManager(settings.data_dir)

    def validate(self) -> None:
        url = self.environments.resolve_url(self.settings.draft_api_url).strip()
        if not url:
            raise ValueError('缺少 COREINSIGHT_DRAFT_API_URL')
        if not url.lower().startswith('https://'):
            raise ValueError('COREINSIGHT_DRAFT_API_URL 必须使用 HTTPS')

    def save(self, result: dict, user_id: str) -> str:
        self.validate()
        operation = str(result.get('operation') or '').strip().lower()
        if operation == 'create':
            return self._create(result, user_id)
        if operation == 'update':
            return self._update(result, user_id)
        raise ValueError('草稿结果 operation 必须是 create 或 update')

    def _create(self, result: dict, user_id: str) -> str:
        if str(result.get('doc_id') or '').strip():
            raise ValueError('新建草稿不能携带 doc_id')
        required = ('title', 'summary', 'experience')
        missing = [key for key in required
                   if not isinstance(result.get(key), str) or not result[key].strip()]
        if missing:
            raise ValueError('新建草稿缺少字段: ' + ', '.join(missing))
        doc_id = uuid.uuid4().hex
        payload = {
            'doc_id': doc_id,
            'user_id': user_id,
            'scene': str(result.get('scene') or '问题定位数据飞轮'),
            'scene_id': str(result.get('scene_id') or '251'),
            'title': result['title'],
            'summary': result['summary'],
            'experience': result['experience'],
        }
        return self._request('post', '/experience/draft/create', payload)

    def _update(self, result: dict, user_id: str) -> str:
        doc_id = str(result.get('doc_id') or '').strip()
        if not doc_id:
            raise ValueError('更新草稿必须携带 doc_id')
        payload = {'user_id': user_id}
        for key in ('title', 'summary', 'experience'):
            if key in result:
                payload[key] = result[key]
        if len(payload) == 1:
            raise ValueError('更新草稿没有可更新字段')
        path = '/experience/draft/' + quote(doc_id, safe='')
        return self._request('put', path, payload)

    def _request(self, method: str, path: str, payload: dict) -> str:
        url = self.environments.resolve_url(
            self.settings.draft_api_url).rstrip('/') + path
        try:
            response = getattr(self.session, method)(
                url, json=payload, timeout=60, verify=False)
            body = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f'草稿接口调用失败: {exc}') from exc
        except ValueError as exc:
            raise RuntimeError('草稿接口返回的不是 JSON') from exc
        message = str(body.get('msg') or '草稿写入失败') if isinstance(body, dict) else '草稿写入失败'
        if response.status_code >= 400:
            raise RuntimeError(message)
        data = body.get('data') if isinstance(body, dict) else None
        returned_id = data.get('id') if isinstance(data, dict) else None
        # 平台统一响应信封使用 code=200；保留对草稿接口旧 code=0 的兼容。
        if (not isinstance(body, dict) or body.get('code') not in (0, 200)
                or not returned_id):
            raise RuntimeError(message)
        logger.info('draft saved operation=%s doc_id=%s', method, returned_id)
        return str(returned_id)
