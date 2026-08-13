from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from datetime import datetime, timezone
from html import escape
from pathlib import Path


_ROOT = Path(tempfile.gettempdir()) / "coreinsight-welink-imports"
_LOCK = threading.RLock()


def _safe_id(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 100 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in value):
        raise ValueError("invalid importId")
    return value


def _dir(import_id: str) -> Path:
    return _ROOT / _safe_id(import_id)


def create_import(import_id: str, metadata: dict) -> dict:
    target = _dir(import_id)
    with _LOCK:
        target.mkdir(parents=True, exist_ok=True)
        meta_path = target / "meta.json"
        if meta_path.exists():
            existing = json.loads(meta_path.read_text("utf-8"))
            return existing
        stored = {**metadata, "importId": import_id, "status": "uploading", "receivedChunks": []}
        meta_path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), "utf-8")
        return stored


def save_chunk(import_id: str, index: int, messages: list[dict]) -> dict:
    if index < 0:
        raise ValueError("chunk index must be non-negative")
    target = _dir(import_id)
    meta_path = target / "meta.json"
    if not meta_path.exists():
        raise KeyError(import_id)
    payload = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    with _LOCK:
        chunk_path = target / f"chunk-{index:08d}.json"
        if chunk_path.exists():
            current = chunk_path.read_text("utf-8")
            if hashlib.sha256(current.encode("utf-8")).hexdigest() != digest:
                raise ValueError("chunk index already exists with different content")
        else:
            chunk_path.write_text(payload, "utf-8")
        meta = json.loads(meta_path.read_text("utf-8"))
        received = set(meta.get("receivedChunks") or [])
        received.add(index)
        meta["receivedChunks"] = sorted(received)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    return {"index": index, "count": len(messages), "sha256": digest}


def load_complete(import_id: str, chunk_count: int, message_count: int) -> tuple[dict, list[dict]]:
    target = _dir(import_id)
    meta_path = target / "meta.json"
    if not meta_path.exists():
        raise KeyError(import_id)
    meta = json.loads(meta_path.read_text("utf-8"))
    expected = list(range(chunk_count))
    if meta.get("receivedChunks") != expected:
        raise ValueError("上传分块不完整")
    messages = []
    for index in expected:
        messages.extend(json.loads((target / f"chunk-{index:08d}.json").read_text("utf-8")))
    if len(messages) != message_count:
        raise ValueError(f"消息总数不一致：expected={message_count}, actual={len(messages)}")
    by_id = {str(item.get("id") or ""): item for item in messages if item.get("id")}
    return meta, sorted(by_id.values(), key=lambda item: (int(item.get("timestamp") or 0), str(item.get("id") or "")))


def mark_status(import_id: str, status: str, chat_id: str = "") -> None:
    meta_path = _dir(import_id) / "meta.json"
    with _LOCK:
        meta = json.loads(meta_path.read_text("utf-8"))
        meta["status"] = status
        if chat_id:
            meta["chatId"] = chat_id
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")


def get_import(import_id: str) -> dict:
    meta_path = _dir(import_id) / "meta.json"
    if not meta_path.exists():
        raise KeyError(import_id)
    return json.loads(meta_path.read_text("utf-8"))


def messages_to_markdown(messages: list[dict]) -> str:
    rows = []
    for item in messages:
        timestamp = int(item.get("timestamp") or 0)
        time_text = datetime.fromtimestamp(timestamp / 1000, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S") if timestamp else ""
        sender = str(item.get("sender") or "")
        content = str(item.get("rawContent") or item.get("content") or "")
        rows.append(f"### {sender}（{time_text}）\n\n{content}\n")
    return "\n".join(rows)
