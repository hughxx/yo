from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


logger = logging.getLogger(__name__)
PRODUCTION = 'production'
TESTING = 'testing'
PRODUCTION_HOST = 'coreinsight.rnd.huawei.com'
TESTING_HOST = 'coreinsight-beta.rnd.huawei.com'
PRODUCTION_ENGINE_HOST = 'fuyao.rnd.huawei.com'
TESTING_ENGINE_HOST = 'coremlops-beta.rnd.huawei.com'
ENVIRONMENTS = (PRODUCTION, TESTING)


class EnvironmentManager:
    def __init__(self, data_dir: Path):
        self.path = data_dir / 'environment.json'
        self._lock = threading.RLock()

    def current(self, fallback_url: str = '') -> str:
        with self._lock:
            try:
                value = json.loads(self.path.read_text(encoding='utf-8')).get('environment')
                if value in ENVIRONMENTS:
                    return value
            except (OSError, ValueError, AttributeError):
                pass
        try:
            host = (urlsplit(fallback_url).hostname or '').lower()
        except ValueError:
            host = ''
        return TESTING if host == TESTING_HOST else PRODUCTION

    def set(self, environment: str) -> None:
        if environment not in ENVIRONMENTS:
            raise ValueError('environment 必须是 production 或 testing')
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(
                json.dumps({'environment': environment}, ensure_ascii=False),
                encoding='utf-8')
            temporary.replace(self.path)
        logger.info('environment switched environment=%s', environment)

    def apply(self, settings) -> None:
        """Apply the selected environment to all known service URL settings."""
        environment = self.current(getattr(settings, 'portal_url', ''))
        coreinsight_source = PRODUCTION_HOST if environment == TESTING else TESTING_HOST
        coreinsight_target = TESTING_HOST if environment == TESTING else PRODUCTION_HOST
        engine_source = (PRODUCTION_ENGINE_HOST if environment == TESTING
                         else TESTING_ENGINE_HOST)
        engine_target = (TESTING_ENGINE_HOST if environment == TESTING
                         else PRODUCTION_ENGINE_HOST)
        for name, value in vars(settings).items():
            if not isinstance(value, str):
                continue
            value = value.replace(coreinsight_source, coreinsight_target)
            if name in {'experience_engine_url', 'ocr_url', 'image_file_server_url'}:
                value = value.replace(engine_source, engine_target)
            setattr(settings, name, value)

    def resolve_url(self, url: str) -> str:
        if not url:
            return url
        try:
            parts = urlsplit(url)
        except ValueError:
            return url
        if (parts.hostname or '').lower() not in (PRODUCTION_HOST, TESTING_HOST):
            return url
        host = TESTING_HOST if self.current(url) == TESTING else PRODUCTION_HOST
        port = f':{parts.port}' if parts.port else ''
        return urlunsplit((parts.scheme, host + port, parts.path, parts.query, parts.fragment))

    def label(self, fallback_url: str = '') -> str:
        return '测试环境' if self.current(fallback_url) == TESTING else '生产环境'
