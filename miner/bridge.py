from __future__ import annotations
import json
import logging
import re
import sys
import threading
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

import requests

from . import config

ROOT = Path(__file__).resolve().parent.parent
PYQT = ROOT / "pyqt_client"
if str(PYQT) not in sys.path:
    sys.path.insert(0, str(PYQT))

from modules.email import outlook  # noqa: E402
from modules.email.html2md import html2md  # noqa: E402
from modules.welink import history  # noqa: E402


def _safe_name(value: str, fallback: str = "未命名") -> str:
    value = re.sub(r'[\\/:*?"<>|\r\n]+', "_", str(value or "")).strip(" .")
    return (value or fallback)[:120]


def _now_name(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


class MinerApi:
    def __init__(self):
        self._window = None
        self._events = []
        self._lock = threading.Lock()
        self._welink_cache = {}
        self._mail_cache = {}

    def bind_window(self, window):
        self._window = window

    def _event(self, message, **data):
        with self._lock:
            self._events.append({"time": datetime.now().strftime("%H:%M:%S"), "message": message, **data})
            self._events = self._events[-200:]

    def poll(self):
        with self._lock:
            items, self._events = self._events[:], []
        return {"items": items}

    def list_folders(self):
        try:
            return {"ok": True, "items": outlook.folder_list()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def list_emails(self, folders=None, search=""):
        try:
            items = outlook.mail_list(folders or None)
            q = str(search or "").strip().lower()
            if q:
                items = [x for x in items if q in " ".join(str(x.get(k, "")) for k in ("subject", "sender_name", "sender_email", "received_time")).lower()]
            return {"ok": True, "items": [x for x in items if not x.get("_diag") and not x.get("_folder_error")]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def fetch_welink(self, group_id, group_name, start_time="", end_time=""):
        try:
            start = int(datetime.fromisoformat(start_time).timestamp() * 1000) if start_time else 0
            end = int(datetime.fromisoformat(end_time).timestamp() * 1000) if end_time else 0
            source = {"type": "group", "source_id": str(group_id)}
            cache_key = (str(group_id), str(start_time or ""), str(end_time or ""))
            if cache_key in self._welink_cache:
                return {"ok": True, "items": self._welink_cache[cache_key], "groupName": group_name or group_id}
            self._event("正在读取聊天记录")
            messages = history.fetch_history(source, start, end, lambda p, n, t: self._event(f"聊天记录读取中：{n} 条"))
            history.enrich_images_inplace(messages, config.IMAGE_PROXY_URL, self._event) if config.IMAGE_PROXY_URL else None
            self._welink_cache[cache_key] = messages
            return {"ok": True, "items": messages, "groupName": group_name or group_id}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def export_welink(self, group_id, group_name, start_time, end_time, selected=None):
        result = self.fetch_welink(group_id, group_name, start_time, end_time)
        if not result["ok"]:
            return result
        selected = None if selected is None else set(str(x) for x in selected)
        messages = result["items"] if selected is None else [x for x in result["items"] if str(x.get("id")) in selected]
        if not messages:
            return {"ok": False, "error": "未选择聊天消息"}
        title = f"{_safe_name(group_name or group_id)}_{start_time or '全部'}_{end_time or '全部'}"
        path = config.WELINK_DIR / f"{_safe_name(title)}.md"
        body = f"# {group_name or group_id}\n\n"
        body += "\n\n".join(f"### {x.get('time','')} {x.get('sender','')}\n\n{x.get('content','')}" for x in messages)
        path.write_text(body, encoding="utf-8")
        self._write_meta(path, "welink", {"group_id": str(group_id), "group_name": group_name, "start_time": start_time, "end_time": end_time, "message_ids": [x.get("id") for x in messages]})
        return {"ok": True, "path": str(path), "count": len(messages)}

    def export_outlook(self, item_ids, folders=None):
        try:
            summaries = {x.get("item_id"): x for x in outlook.mail_list(folders or None)}
            selected = [summaries[str(x)] for x in item_ids if str(x) in summaries]
            if not selected:
                raise ValueError("未选择邮件")
            parts = []
            for source in selected:
                item = outlook.mail_get(source["item_id"], config.IMAGE_PROXY_URL)
                parts.append(f"# {item.get('subject') or '无主题'}\n\n- 发件人：{item.get('sender_name','')} {item.get('sender_email','')}\n- 时间：{item.get('received_time','')}\n\n{item.get('markdown_body') or html2md(item.get('html_body',''))}")
            title = _safe_name(selected[0].get("subject") or "邮件提取")
            if len(selected) > 1:
                title += f"_等{len(selected)}封"
            path = config.OUTLOOK_DIR / f"{title}.md"
            path.write_text("\n\n---\n\n".join(parts), encoding="utf-8")
            self._write_meta(path, "outlook", {"item_ids": [x.get("item_id") for x in selected], "folders": folders or []})
            return {"ok": True, "path": str(path), "count": len(selected)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def extract_experience(self, markdown_path):
        try:
            path = Path(markdown_path).resolve()
            if path.suffix.lower() != ".md" or not path.is_file():
                raise ValueError("Markdown 文件不存在")
            text = path.read_text(encoding="utf-8")
            self._event("正在调用大模型提取经验")
            payload = {"model": config.LLM_MODEL_ID, "messages": [{"role": "user", "content": config.PROMPT + text}], "temperature": 0.2, "stream": False}
            response = requests.post(config.LLM_BASE_URL.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"}, json=payload, timeout=999, verify=False)
            response.raise_for_status()
            experience = response.json()["choices"][0]["message"]["content"].strip()
            out = path.with_suffix(".experience.md")
            out.write_text(experience, encoding="utf-8")
            return {"ok": True, "path": str(out), "source": str(path)}
        except Exception as exc:
            logging.exception("miner experience extraction failed")
            return {"ok": False, "error": str(exc)}

    def list_results(self):
        result = []
        for kind, directory in (("welink", config.WELINK_DIR), ("outlook", config.OUTLOOK_DIR)):
            for path in sorted(directory.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
                if path.name.endswith(".experience.md"):
                    continue
                exp = path.with_suffix(".experience.md")
                result.append({"kind": kind, "title": path.stem, "markdown": str(path), "experience": str(exp) if exp.exists() else "", "hasExperience": exp.exists(), "updatedAt": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
        return {"ok": True, "items": result}

    def open_results_dir(self):
        import os
        os.startfile(str(config.ROOT)) if hasattr(os, "startfile") else webbrowser.open(config.ROOT.as_uri())
        return {"ok": True, "path": str(config.ROOT)}

    def open_file(self, path):
        import os
        target = Path(path).resolve()
        if target.suffix.lower() not in (".md", ".json") or not target.is_file():
            return {"ok": False, "error": "文件不存在或类型不支持"}
        os.startfile(str(target)) if hasattr(os, "startfile") else webbrowser.open(target.as_uri())
        return {"ok": True}

    @staticmethod
    def _write_meta(path, kind, data):
        meta = dict(data, kind=kind, markdown=str(path), created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
