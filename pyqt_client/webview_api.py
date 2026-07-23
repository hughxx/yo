"""JSON-only business facade exposed through pywebview's JavaScript Bridge."""
from __future__ import annotations

import json
import logging
import uuid
import webbrowser

import backend
import store
from modules.email import rules as email_rules
from modules.welink import rules as welink_rules
from runtime import EmailRuntime, EmailScheduler, EventStream, WelinkRuntime, WelinkScheduler
from version import APP_VERSION


class AppApi:
    SERVER_PRESETS = [
        {"label": "云核心网", "value": "https://coreinsight-beta.rnd.huawei.com/collection"},
        {"label": "离线（仅本地导出）", "value": backend.OFFLINE},
    ]

    def __init__(self):
        self._window = None
        self._host = None
        self.events = EventStream()
        self.email = EmailRuntime(self.events)
        self.email_scheduler = EmailScheduler(self.email, self.events)
        self.welink = WelinkRuntime(self.events)
        self.welink_scheduler = WelinkScheduler(self.welink, self.events)

    def bind_window(self, window) -> None:
        self._window = window

    def bind_host(self, host) -> None:
        self._host = host

    @staticmethod
    def _ok(**data) -> dict:
        return {"ok": True, **data}

    @staticmethod
    def _error(exc) -> dict:
        logging.getLogger("bridge").exception("操作失败：%s", exc)
        return {"ok": False, "error": str(exc)}

    @staticmethod
    def _configured(settings: dict) -> bool:
        if backend.is_offline_url(settings.get("backendUrl", "")):
            return bool(settings.get("outputDir"))
        return bool(settings.get("backendUrl") and settings.get("userId") and settings.get("namespace"))

    def bootstrap(self) -> dict:
        settings = store.load_settings()
        backend.set_base(settings.get("backendUrl", ""))
        return self._ok(
            version=APP_VERSION,
            settings=settings,
            configured=self._configured(settings),
            serverPresets=self.SERVER_PRESETS,
            rules=email_rules.load(),
            blacklist=email_rules.load_blacklist(),
            welinkSources=welink_rules.load(),
            emailTask=self.email.status(),
            emailSchedule=self.email_scheduler.status(),
            welinkTask=self.welink.status(),
            welinkSchedule=self.welink_scheduler.status(),
        )

    def poll_events(self, after: int = 0) -> dict:
        return self._ok(**self.events.read(after))

    # ── settings / setup / version ──────────────────────────────
    def save_settings(self, settings: dict) -> dict:
        try:
            merged = {**store.load_settings(), **(settings or {})}
            json.loads(merged.get("customJsonConfig") or "{}")
            merged["scanIntervalMinutes"] = max(1, min(1440, int(merged.get("scanIntervalMinutes", 60))))
            merged["welinkPollInterval"] = max(1, int(merged.get("welinkPollInterval", 3)))
            if not merged.get("backendUrl"):
                raise ValueError("请选择或输入服务器地址")
            if backend.is_offline_url(merged["backendUrl"]):
                merged["namespace"] = ""
                if not merged.get("outputDir"):
                    raise ValueError("离线模式请先设置文件保存目录")
            else:
                if not merged.get("userId"):
                    raise ValueError("请搜索并从结果中选择工号")
                if not merged.get("namespace"):
                    raise ValueError("请选择命名空间")
            store.save_settings(merged)
            backend.set_base(merged.get("backendUrl", ""))
            self.events.emit("system", "设置已保存", type="settings")
            return self._ok(settings=merged, configured=self._configured(merged))
        except Exception as exc:
            return self._error(exc)

    def test_server(self, url: str) -> dict:
        if backend.is_offline_url(url):
            return self._ok(reachable=True, offline=True)
        backend.set_base(url)
        return self._ok(reachable=backend.ping(), offline=False)

    def get_namespaces(self, url: str = "") -> dict:
        try:
            if backend.is_offline_url(url):
                return self._ok(items=[])
            if url:
                backend.set_base(url)
            return self._ok(items=backend.get_namespaces())
        except Exception as exc:
            return self._error(exc)

    def get_userinfo(self, query: str, url: str = "") -> dict:
        try:
            if not query.strip() or backend.is_offline_url(url):
                return self._ok(items=[])
            if url:
                backend.set_base(url)
            return self._ok(items=backend.get_userinfo(query.strip()))
        except Exception as exc:
            return self._error(exc)

    def choose_output_dir(self) -> dict:
        try:
            import webview
            dialog_type = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
            result = self._window.create_file_dialog(dialog_type)
            return self._ok(path=result[0] if result else "")
        except Exception as exc:
            return self._error(exc)

    def version_info(self) -> dict:
        settings = store.load_settings()
        if not settings.get("backendUrl") or backend.is_offline_url(settings.get("backendUrl", "")):
            return self._ok(info={})
        backend.set_base(settings["backendUrl"])
        return self._ok(info=backend.get_latest_version())

    def open_external(self, url: str) -> dict:
        try:
            webbrowser.open(url)
            return self._ok()
        except Exception as exc:
            return self._error(exc)

    def quit_app(self) -> dict:
        if self._host:
            threading.Thread(target=self._host.quit, daemon=True).start()
        return self._ok()

    # ── Outlook mail ─────────────────────────────────────────────
    def list_folders(self) -> dict:
        try:
            items = self.email.list_folders()
            self.events.emit("email", f"读取 Outlook 文件夹：{len(items)} 个", type="outlook_folders")
            return self._ok(items=items)
        except Exception as exc:
            return self._error(exc)

    def list_emails(self) -> dict:
        try:
            result = self.email.list_emails()
            self.events.emit("email", f"读取 Outlook 邮件：{len(result['items'])} 封", type="outlook_emails")
            return self._ok(**result)
        except Exception as exc:
            return self._error(exc)

    def parse_status(self, topics: list[str]) -> dict:
        try:
            settings = store.load_settings()
            if backend.is_offline_url(settings.get("backendUrl", "")):
                return self._ok(items={})
            backend.set_base(settings.get("backendUrl", ""))
            return self._ok(items=backend.get_parse_status(topics, settings.get("namespace", "")))
        except Exception as exc:
            return self._error(exc)

    def preview_email_rule(self, rules: list[dict]) -> dict:
        try:
            if isinstance(rules, dict):
                rules = [rules]
            return self._ok(itemIds=self.email.preview_rules(rules or []))
        except Exception as exc:
            return self._error(exc)

    def start_email_processing(self, item_ids: list[str]) -> dict:
        try:
            if not item_ids:
                raise ValueError("未选择邮件")
            return self._ok(task=self.email.start(item_ids, True, False, "处理选中"))
        except Exception as exc:
            return self._error(exc)

    def cancel_email_processing(self) -> dict:
        return self._ok(task=self.email.cancel())

    def email_task_status(self) -> dict:
        return self._ok(task=self.email.status(), schedule=self.email_scheduler.status())

    def start_email_schedule(self, mode: str, interval: int, daily_time: str) -> dict:
        try:
            return self._ok(schedule=self.email_scheduler.start(mode, interval, daily_time))
        except Exception as exc:
            return self._error(exc)

    def stop_email_schedule(self) -> dict:
        return self._ok(schedule=self.email_scheduler.stop())

    # ── email rules ──────────────────────────────────────────────
    def save_rules(self, kind: str, rules: list[dict]) -> dict:
        try:
            normalized = []
            for rule in rules or []:
                name = str(rule.get("name", "")).strip()
                if not name:
                    raise ValueError("规则名称不能为空")
                normalized.append({
                    "id": rule.get("id") or str(uuid.uuid4()),
                    "name": name,
                    "keywords": [str(x).strip() for x in rule.get("keywords", []) if str(x).strip()],
                    "body_keywords": [str(x).strip() for x in rule.get("body_keywords", []) if str(x).strip()],
                    "senders": [str(x).strip() for x in rule.get("senders", []) if str(x).strip()],
                    "logic": "AND" if rule.get("logic") == "AND" else "OR",
                })
            (email_rules.save_blacklist if kind == "blacklist" else email_rules.save)(normalized)
            self.events.emit("email", "规则已变更，请刷新邮件重新匹配", type="rules_changed", refresh=True)
            return self._ok(items=normalized)
        except Exception as exc:
            return self._error(exc)

    # ── WeLink history mining ────────────────────────────────────
    def save_welink_sources(self, sources: list[dict]) -> dict:
        try:
            normalized = []
            seen = set()
            for source in sources or []:
                source_type = "user" if source.get("type") == "user" else "group"
                source_id = str(source.get("source_id", "")).strip()
                source_name = str(source.get("source_name", "")).strip()
                if not source_id or not source_name:
                    raise ValueError("来源 ID 和显示名称均不能为空")
                key = (source_type, source_id)
                if key in seen:
                    raise ValueError(f"聊天来源重复：{source_name}")
                seen.add(key)
                normalized.append({
                    "id": source.get("id") or str(uuid.uuid4()),
                    "type": source_type,
                    "source_id": source_id,
                    "source_name": source_name,
                    "enabled": bool(source.get("enabled", True)),
                })
            welink_rules.save(normalized)
            stopped = self.welink_scheduler.status().get("active", False)
            schedule = self.welink_scheduler.stop() if stopped else self.welink_scheduler.status()
            return self._ok(items=normalized, schedule=schedule, scheduleStopped=stopped)
        except Exception as exc:
            return self._error(exc)

    def list_welink_history(self, source: dict, start_ms: int = 0, end_ms: int = 0) -> dict:
        try:
            items = self.welink.list_history(source or {}, start_ms, end_ms)
            self.events.emit("welink", f"读取聊天记录：{len(items)} 条", type="welink_history")
            return self._ok(items=items)
        except Exception as exc:
            return self._error(exc)

    def start_welink_processing(self, jobs: list[dict]) -> dict:
        try:
            return self._ok(task=self.welink.start(jobs or [], "处理选中"))
        except Exception as exc:
            return self._error(exc)

    def cancel_welink_processing(self) -> dict:
        return self._ok(task=self.welink.cancel())

    def welink_task_status(self) -> dict:
        return self._ok(task=self.welink.status(), schedule=self.welink_scheduler.status())

    def start_welink_schedule(self, sources: list[dict], mode: str, interval: int,
                              daily_time: str, range_mode: str) -> dict:
        try:
            schedule = self.welink_scheduler.start(
                sources or [], mode, interval, daily_time, range_mode
            )
            return self._ok(schedule=schedule)
        except Exception as exc:
            return self._error(exc)

    def stop_welink_schedule(self) -> dict:
        return self._ok(schedule=self.welink_scheduler.stop())

    def shutdown(self, *_args) -> None:
        self.email_scheduler.shutdown()
        self.welink_scheduler.shutdown()
        self.email.cancel()
        self.welink.cancel()
