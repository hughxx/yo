from __future__ import annotations

import json
import threading
from pathlib import Path

from .models import GroupConfig, GroupCreate


def _dump(model: GroupConfig) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class GroupStore:
    def __init__(self, data_dir: Path):
        self._path = data_dir / "welink_groups.json"
        self._lock = threading.RLock()
        self._recover_interrupted()

    def _recover_interrupted(self) -> None:
        with self._lock:
            rows = self._read()
            changed = False
            for row in rows:
                if row.get("status") == "extracting":
                    row["status"] = "scheduled" if row.get("scheduleEnabled") else "idle"
                    changed = True
            if changed:
                self._write(rows)

    def _read(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, groups: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self._path)

    @staticmethod
    def _normalized(raw: dict) -> GroupConfig:
        return GroupConfig(**raw)

    def list(self) -> list[GroupConfig]:
        with self._lock:
            result = []
            for row in self._read():
                try:
                    result.append(self._normalized(row))
                except Exception:
                    continue
            return result

    def get(self, group_id: str) -> GroupConfig | None:
        key = group_id.strip()
        return next((group for group in self.list() if group.groupId == key), None)

    def add(self, group: GroupCreate) -> GroupConfig:
        group_id = group.groupId.strip()
        name = group.name.strip()
        with self._lock:
            groups = self.list()
            if any(item.groupId == group_id for item in groups):
                raise ValueError("该 WeLink 群组已添加")
            created = GroupConfig(groupId=group_id, name=name)
            self._write([_dump(item) for item in [*groups, created]])
            return created

    def update(self, group: GroupConfig) -> GroupConfig:
        group.groupId = group.groupId.strip()
        group.name = group.name.strip()
        with self._lock:
            groups = self.list()
            for index, current in enumerate(groups):
                if current.groupId == group.groupId:
                    groups[index] = group
                    self._write([_dump(item) for item in groups])
                    return group
        raise KeyError(group.groupId)

    def delete(self, group_id: str) -> None:
        key = group_id.strip()
        with self._lock:
            groups = self.list()
            kept = [item for item in groups if item.groupId != key]
            if len(kept) == len(groups):
                raise KeyError(key)
            self._write([_dump(item) for item in kept])

    def set_status(self, group_id: str, status: str) -> GroupConfig:
        group = self.get(group_id)
        if not group:
            raise KeyError(group_id)
        group.status = status
        return self.update(group)
