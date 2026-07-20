"""Python business facade exposed through pywebview's JavaScript Bridge."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

import backend
import store
from modules.email import local_archive, outlook, rules as email_rules
from modules.welink import chatlog_import, rules as welink_rules
from modules.welink.monitor import WelinkMonitor
from version import APP_VERSION


class AppApi:
    """All public methods return JSON-serialisable envelopes for predictable UI errors."""

    def __init__(self):
        self._window = None
        self._outlook_lock = threading.Lock()
        self._monitor = None
        self._monitor_events = []
        self._monitor_lock = threading.Lock()

    def bind_window(self, window) -> None:
        self._window = window

    @staticmethod
    def _ok(**data) -> dict:
        return {"ok": True, **data}

    @staticmethod
    def _error(exc) -> dict:
        return {"ok": False, "error": str(exc)}

    def bootstrap(self) -> dict:
        settings = store.load_settings()
        backend.set_base(settings.get("backendUrl", ""))
        return self._ok(
            version=APP_VERSION,
            settings=settings,
            rules=email_rules.load(),
            blacklist=email_rules.load_blacklist(),
            welinkRules=welink_rules.load(),
            platform=os.name,
        )

    def save_settings(self, settings: dict) -> dict:
        try:
            merged = {**store.load_settings(), **(settings or {})}
            json.loads(merged.get("customJsonConfig") or "{}")
            merged["scanIntervalMinutes"] = max(1, int(merged.get("scanIntervalMinutes", 60)))
            merged["welinkPollInterval"] = max(1, int(merged.get("welinkPollInterval", 3)))
            store.save_settings(merged)
            backend.set_base(merged.get("backendUrl", ""))
            return self._ok(settings=merged)
        except Exception as exc:
            return self._error(exc)

    def test_server(self, url: str) -> dict:
        backend.set_base(url)
        return self._ok(reachable=backend.ping())

    def get_namespaces(self, url: str = "") -> dict:
        try:
            if url:
                backend.set_base(url)
            return self._ok(items=backend.get_namespaces())
        except Exception as exc:
            return self._error(exc)

    def get_userinfo(self, query: str, url: str = "") -> dict:
        try:
            if url:
                backend.set_base(url)
            return self._ok(items=backend.get_userinfo(query))
        except Exception as exc:
            return self._error(exc)

    def choose_output_dir(self) -> dict:
        try:
            import webview
            dialog_type = (webview.FileDialog.FOLDER if hasattr(webview, "FileDialog")
                           else webview.FOLDER_DIALOG)
            result = self._window.create_file_dialog(dialog_type)
            return self._ok(path=result[0] if result else "")
        except Exception as exc:
            return self._error(exc)

    def choose_zip(self) -> dict:
        try:
            import webview
            dialog_type = (webview.FileDialog.OPEN if hasattr(webview, "FileDialog")
                           else webview.OPEN_DIALOG)
            result = self._window.create_file_dialog(
                dialog_type, file_types=("ZIP archive (*.zip)",)
            )
            return self._ok(path=result[0] if result else "")
        except Exception as exc:
            return self._error(exc)

    def list_folders(self) -> dict:
        try:
            return self._ok(items=outlook.folder_list())
        except Exception as exc:
            return self._error(exc)

    @staticmethod
    def _match(items: list, scan_folders: list) -> list:
        whitelist = email_rules.load()
        blacklist = email_rules.load_blacklist()
        wl_maps = email_rules.build_match_maps(whitelist, scan_folders)
        bl_maps = email_rules.build_match_maps(blacklist, scan_folders)
        for item in items:
            if item.get("_diag") or item.get("_folder_error"):
                continue
            allowed = email_rules.match(item, whitelist, wl_maps)
            blocked = email_rules.match(item, blacklist, bl_maps)
            item["matched_rule"] = allowed if allowed and not blocked else ""
            item["parseStatus"] = "-"
        return items

    def list_emails(self) -> dict:
        if not self._outlook_lock.acquire(blocking=False):
            return self._error("已有 Outlook 操作正在执行")
        try:
            settings = store.load_settings()
            folders = settings.get("scanFolders") or []
            raw = self._match(outlook.mail_list(folders or None), folders)
            return self._ok(
                items=[x for x in raw if not x.get("_diag") and not x.get("_folder_error")],
                errors=[x["_folder_error"] for x in raw if x.get("_folder_error")],
                diagnostics=[x["_diag"] for x in raw if x.get("_diag")],
            )
        except Exception as exc:
            return self._error(exc)
        finally:
            self._outlook_lock.release()

    def parse_status(self, topics: list[str]) -> dict:
        try:
            settings = store.load_settings()
            backend.set_base(settings.get("backendUrl", ""))
            return self._ok(items=backend.get_parse_status(topics, settings.get("namespace", "")))
        except Exception as exc:
            return self._error(exc)

    def process_emails(self, item_ids: list[str], force: bool = True) -> dict:
        if not item_ids:
            return self._error("未选择邮件")
        if not self._outlook_lock.acquire(blocking=False):
            return self._error("已有 Outlook 操作正在执行")
        succeeded, failed, messages = 0, 0, []
        try:
            settings = store.load_settings()
            backend.set_base(settings.get("backendUrl", ""))
            offline = backend.is_offline_url(settings.get("backendUrl", ""))
            img_api = "" if offline else settings.get("backendUrl", "")
            extra = json.loads(settings.get("customJsonConfig") or "{}")
            folders = settings.get("scanFolders") or []
            summaries = self._match(outlook.mail_list(folders or None), folders)
            lookup = {x.get("item_id"): x for x in summaries}
            for item_id in item_ids:
                try:
                    item = outlook.mail_get(item_id, img_api)
                    source = lookup.get(item_id, {})
                    if not offline:
                        backend.receive_email({
                            "EmailId": item["item_id"],
                            "ConversationTopic": item.get("conversation_topic", ""),
                            "Subject": item.get("subject", ""),
                            "SenderName": item.get("sender_name", ""),
                            "SenderEmail": item.get("sender_email", ""),
                            "ReceivedTime": item.get("received_time", ""),
                            "HtmlBody": item.get("html_body", ""),
                            "MarkdownBody": item.get("markdown_body", ""),
                            "MatchedRuleName": source.get("matched_rule") or "手动处理",
                            "UserId": settings.get("userId", ""),
                            "Namespace": settings.get("namespace", ""),
                            "ExtraInfo": extra,
                            "Force": bool(force),
                        })
                    local_archive.save_email(
                        settings.get("outputDir", ""),
                        item.get("subject") or item.get("conversation_topic", ""),
                        item.get("html_body", ""), item.get("markdown_body", ""),
                    )
                    succeeded += 1
                except Exception as exc:
                    failed += 1
                    messages.append(f"{item_id}: {exc}")
            settings["lastSyncTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            store.save_settings(settings)
            return self._ok(success=succeeded, failed=failed, messages=messages)
        except Exception as exc:
            return self._error(exc)
        finally:
            self._outlook_lock.release()

    def save_rules(self, kind: str, rules: list[dict]) -> dict:
        try:
            normalized = []
            for rule in rules or []:
                normalized.append({
                    "id": rule.get("id") or str(uuid.uuid4()),
                    "name": str(rule.get("name", "")).strip(),
                    "keywords": list(rule.get("keywords") or []),
                    "body_keywords": list(rule.get("body_keywords") or []),
                    "senders": list(rule.get("senders") or []),
                    "logic": "AND" if rule.get("logic") == "AND" else "OR",
                    "enabled": bool(rule.get("enabled", True)),
                })
            (email_rules.save_blacklist if kind == "blacklist" else email_rules.save)(normalized)
            return self._ok(items=normalized)
        except Exception as exc:
            return self._error(exc)

    def save_welink_rules(self, rules: list[dict]) -> dict:
        try:
            normalized = [{
                "id": rule.get("id") or str(uuid.uuid4()),
                "group_id": str(rule.get("group_id", "")).strip(),
                "group_name": str(rule.get("group_name", "")).strip(),
            } for rule in (rules or [])]
            welink_rules.save(normalized)
            return self._ok(items=normalized)
        except Exception as exc:
            return self._error(exc)

    def toggle_welink_monitor(self, start: bool) -> dict:
        try:
            if start:
                if self._monitor and self._monitor.isRunning():
                    return self._ok(running=True)
                settings = store.load_settings()
                self._monitor = WelinkMonitor(
                    backend_base=settings.get("backendUrl", "http://localhost:8023"),
                    start_cmd=settings.get("welinkStartCmd", "@云见 开始定位"),
                    end_cmd=settings.get("welinkEndCmd", "@云见 结束定位"),
                    summary_cmd=settings.get("welinkSummaryCmd", "@云见 总结经验"),
                    user_id=settings.get("welinkUserId") or settings.get("userId", ""),
                    poll_interval=int(settings.get("welinkPollInterval", 3)),
                )
                self._monitor.log_signal.connect(self._monitor_event)
                self._monitor.uploaded_signal.connect(
                    lambda info: self._monitor_event(f"归档完成：{info.get('group_name', '')}，{info.get('count', 0)} 条")
                )
                self._monitor.start()
            elif self._monitor:
                self._monitor.stop()
                self._monitor.wait(4000)
                self._monitor = None
            return self._ok(running=bool(self._monitor and self._monitor.isRunning()))
        except Exception as exc:
            return self._error(exc)

    def _monitor_event(self, text: str) -> None:
        with self._monitor_lock:
            self._monitor_events.append(str(text))

    def welink_monitor_status(self, after: int = 0) -> dict:
        with self._monitor_lock:
            events = self._monitor_events[max(0, int(after)):]
            cursor = len(self._monitor_events)
        return self._ok(
            running=bool(self._monitor and self._monitor.isRunning()),
            events=events,
            cursor=cursor,
        )

    def shutdown(self, *_args) -> None:
        if self._monitor:
            self._monitor.stop()
            self._monitor.wait(3000)

    def import_welink(self, zip_path: str, group_name: str = "") -> dict:
        try:
            if not zip_path or Path(zip_path).suffix.lower() != ".zip":
                raise ValueError("请选择 ZIP 格式的聊天记录")
            settings = store.load_settings()
            backend.set_base(settings.get("backendUrl", ""))
            offline = backend.is_offline_url(settings.get("backendUrl", ""))
            stem, text, images = chatlog_import.read_zip(zip_path)
            messages = chatlog_import.parse_chatlog(text)
            if not messages:
                raise ValueError("未解析到任何消息，请确认聊天记录格式")
            match = chatlog_import.match_images(messages, images)
            if not offline:
                seen = set()
                for image in [x for x in match["assign"] if x] + list(match["leftover"]):
                    if id(image) in seen:
                        continue
                    seen.add(id(image))
                    image["url"] = backend.upload_image(image["data"], image["name"])
            html = chatlog_import.build_html(messages, match)
            name = group_name.strip() or stem
            start_dt, end_dt = messages[0]["ts"], messages[-1]["ts"]
            if offline:
                from modules.email.html2md import html2md
                title = f'{name}_{start_dt.strftime("%Y%m%d_%H%M")}'
                local_archive.save_email(settings.get("outputDir", ""), title, html, html2md(html))
                return self._ok(count=len(messages), offline=True, duplicate=False,
                                summary=match.get("summary", ""))
            chat_id = f'manual_{stem}_{int(start_dt.timestamp()*1000)}_{hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()[:8]}'
            result = backend.receive_welink_chatlog({
                "ChatId": chat_id, "GroupId": stem, "GroupName": name,
                "StartTime": int(start_dt.timestamp() * 1000),
                "EndTime": int(end_dt.timestamp() * 1000), "HtmlBody": html,
                "UploadBy": settings.get("welinkUserId") or settings.get("userId", ""),
            })
            return self._ok(count=len(messages), offline=False,
                            duplicate=bool(result.get("Duplicate")), summary=match.get("summary", ""))
        except Exception as exc:
            return self._error(exc)
