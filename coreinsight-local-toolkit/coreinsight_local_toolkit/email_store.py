from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from .models import EmailConfig


def _dump(model) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class EmailConfigStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "email_config.json"
        self.lock = threading.RLock()

    def get(self) -> EmailConfig:
        with self.lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                return EmailConfig(**raw)
            except (OSError, ValueError, TypeError):
                return EmailConfig()

    def save(self, config: EmailConfig) -> EmailConfig:
        with self.lock:
            for collection in (config.rules, config.blacklist):
                for rule in collection:
                    if not rule.id:
                        rule.id = uuid.uuid4().hex
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(_dump(config), ensure_ascii=False, indent=2),
                encoding="utf-8")
            temporary.replace(self.path)
            return config

    def patch(self, **values) -> EmailConfig:
        config = self.get()
        for key, value in values.items():
            setattr(config, key, value)
        return self.save(config)
