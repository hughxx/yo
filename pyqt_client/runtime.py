"""Long-lived desktop jobs that must not depend on the web page lifecycle."""
from __future__ import annotations

import json
import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta

import backend
import store
from modules.email import local_archive, outlook, rules as email_rules
from modules.email.html2md import html2md
from modules.welink import history as welink_history


class EventStream:
    def __init__(self, limit: int = 1000):
        self._events = []
        self._next_id = 1
        self._limit = limit
        self._lock = threading.Lock()

    def emit(self, category: str, message: str, **data):
        event_type = data.get("type", "event")
        logging.getLogger(f"event.{category}").info("%s | %s", event_type, message)
        with self._lock:
            self._events.append({
                "id": self._next_id,
                "category": category,
                "message": str(message),
                "time": datetime.now().strftime("%H:%M:%S"),
                **data,
            })
            self._next_id += 1
            del self._events[:-self._limit]

    def read(self, after: int = 0) -> dict:
        with self._lock:
            items = [event for event in self._events if event["id"] > int(after or 0)]
            cursor = self._next_id - 1
        return {"events": items, "cursor": cursor}


class EmailRuntime:
    """Serialises Outlook access and owns cancellable mail processing."""

    def __init__(self, events: EventStream):
        self.events = events
        self.outlook_lock = threading.Lock()
        self._cache = []
        self._cache_lock = threading.Lock()
        self._task_lock = threading.Lock()
        self._task = self._idle_task()
        self._cancel = threading.Event()

    @staticmethod
    def _idle_task():
        return {"running": False, "verb": "", "current": 0, "total": 0,
                "success": 0, "failed": 0, "cancelled": False}

    @staticmethod
    def match(items: list, folders: list) -> list:
        whitelist = email_rules.load()
        blacklist = email_rules.load_blacklist()
        wl_maps = email_rules.build_match_maps(whitelist, folders)
        bl_maps = email_rules.build_match_maps(blacklist, folders)
        for item in items:
            if item.get("_diag") or item.get("_folder_error"):
                continue
            allowed = email_rules.match(item, whitelist, wl_maps)
            blocked = email_rules.match(item, blacklist, bl_maps)
            item["matched_rule"] = allowed if allowed and not blocked else ""
            item.setdefault("parseStatus", "-")
        return items

    def list_folders(self) -> list:
        if not self.outlook_lock.acquire(blocking=False):
            raise RuntimeError("已有 Outlook 操作正在执行")
        try:
            return outlook.folder_list()
        finally:
            self.outlook_lock.release()

    def list_emails(self) -> dict:
        if not self.outlook_lock.acquire(blocking=False):
            raise RuntimeError("已有 Outlook 操作正在执行")
        try:
            settings = store.load_settings()
            folders = settings.get("scanFolders") or []
            raw = self.match(outlook.mail_list(folders or None), folders)
            items = [x for x in raw if not x.get("_diag") and not x.get("_folder_error")]
            with self._cache_lock:
                self._cache = items
            return {
                "items": items,
                "errors": [x["_folder_error"] for x in raw if x.get("_folder_error")],
                "diagnostics": [x["_diag"] for x in raw if x.get("_diag")],
            }
        finally:
            self.outlook_lock.release()

    def preview_rules(self, rules: list[dict]) -> list[str]:
        """Return cached mail ids matching any ad-hoc manual filter rule."""
        if not self.outlook_lock.acquire(blocking=False):
            raise RuntimeError("已有 Outlook 操作正在执行")
        try:
            settings = store.load_settings()
            folders = settings.get("scanFolders") or []
            candidates = []
            for index, rule in enumerate(rules or [], 1):
                candidate = {
                    "name": str(rule.get("name", "")).strip() or f"规则 {index}",
                    "keywords": [str(x).strip() for x in rule.get("keywords", []) if str(x).strip()],
                    "body_keywords": [str(x).strip() for x in rule.get("body_keywords", []) if str(x).strip()],
                    "senders": [str(x).strip() for x in rule.get("senders", []) if str(x).strip()],
                    "logic": "AND" if rule.get("logic") == "AND" else "OR",
                }
                if not any(candidate[key] for key in ("keywords", "body_keywords", "senders")):
                    raise ValueError(f"{candidate['name']} 至少填写一个匹配条件")
                candidates.append(candidate)
            if not candidates:
                raise ValueError("请至少添加一条规则")
            maps = email_rules.build_match_maps(candidates, folders)
            with self._cache_lock:
                cached = [dict(item) for item in self._cache]
            return [item["item_id"] for item in cached if email_rules.match(item, candidates, maps)]
        finally:
            self.outlook_lock.release()

    def preview_rule(self, rule: dict) -> list[str]:
        """Compatibility wrapper for callers using a single rule."""
        return self.preview_rules([rule])

    def start(self, item_ids: list[str] | None, force: bool, matched_only: bool, verb: str) -> dict:
        with self._task_lock:
            if self._task["running"]:
                raise RuntimeError("已有邮件处理任务正在执行")
            self._task = {"running": True, "verb": verb, "current": 0, "total": 0,
                          "success": 0, "failed": 0, "cancelled": False}
            self._cancel.clear()
        thread = threading.Thread(
            target=self._run, args=(item_ids, bool(force), bool(matched_only), verb), daemon=True
        )
        thread.start()
        return self.status()

    def cancel(self) -> dict:
        with self._task_lock:
            if self._task["running"]:
                self._cancel.set()
                self.events.emit("email", "正在停止…（当前邮件完成后停止）", type="email_progress")
        return self.status()

    def status(self) -> dict:
        with self._task_lock:
            return dict(self._task)

    def _set_task(self, **changes):
        with self._task_lock:
            self._task.update(changes)

    def _run(self, item_ids, force, matched_only, verb):
        succeeded = failed = attempted = 0
        try:
            if not self.outlook_lock.acquire(blocking=False):
                raise RuntimeError("已有 Outlook 操作正在执行")
            try:
                settings = store.load_settings()
                backend.set_base(settings.get("backendUrl", ""))
                offline = backend.is_offline_url(settings.get("backendUrl", ""))
                extra = json.loads(settings.get("customJsonConfig") or "{}")
                folders = settings.get("scanFolders") or []

                if item_ids is None:
                    raw = self.match(outlook.mail_list(folders or None), folders)
                    summaries = [x for x in raw if not x.get("_diag") and not x.get("_folder_error")]
                else:
                    with self._cache_lock:
                        summaries = [dict(x) for x in self._cache]
                lookup = {x.get("item_id"): x for x in summaries}
                selected = ([x for x in summaries if x.get("matched_rule")] if matched_only
                            else [lookup[i] for i in (item_ids or []) if i in lookup])
                self._set_task(total=len(selected))
                if not selected:
                    self.events.emit("email", "无匹配邮件", type="email_complete", refresh=False)
                    return

                img_api = "" if offline else settings.get("backendUrl", "")
                self.events.emit("email", f"{verb}开始：共 {len(selected)} 封", type="email_progress")
                for batch_start in range(0, len(selected), 10):
                    if self._cancel.is_set():
                        break
                    batch = selected[batch_start:batch_start + 10]
                    for source in batch:
                        if self._cancel.is_set():
                            break
                        try:
                            item = outlook.mail_get(source["item_id"], img_api)
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
                                    "Force": force,
                                })
                            local_archive.save_email(
                                settings.get("outputDir", ""),
                                item.get("subject") or item.get("conversation_topic", ""),
                                item.get("html_body", ""), item.get("markdown_body", ""),
                            )
                            succeeded += 1
                        except Exception as exc:
                            failed += 1
                            self.events.emit("email", f"处理失败：{source.get('subject') or source.get('item_id')}；{exc}", type="email_log")
                        attempted += 1
                        self._set_task(current=attempted, success=succeeded, failed=failed)
                        self.events.emit("email", f"{verb}中… {attempted}/{len(selected)}，成功 {succeeded}，失败 {failed}", type="email_progress")

                latest_settings = store.load_settings()
                latest_settings["lastSyncTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                store.save_settings(latest_settings)
                cancelled = self._cancel.is_set()
                summary = (f"{verb}已停止：已处理 {attempted}/{len(selected)} 封，成功 {succeeded}，失败 {failed}"
                           if cancelled else f"{verb}完成：{len(selected)} 封，成功 {succeeded}，失败 {failed}")
                self._set_task(cancelled=cancelled)
                self.events.emit("email", summary, type="email_complete", refresh=True,
                                 success=succeeded, failed=failed, cancelled=cancelled)
            finally:
                self.outlook_lock.release()
        except Exception as exc:
            failed += 1
            self.events.emit("email", f"{verb}失败：{exc}", type="email_complete", refresh=False,
                             success=succeeded, failed=failed)
        finally:
            self._set_task(running=False, success=succeeded, failed=failed)


class EmailScheduler:
    def __init__(self, runtime: EmailRuntime, events: EventStream):
        self.runtime = runtime
        self.events = events
        self._active = False
        self._mode = "interval"
        self._interval = 60
        self._daily_time = "09:00"
        self._next_run = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def start(self, mode: str, interval: int, daily_time: str) -> dict:
        mode = "daily" if mode == "daily" else "interval"
        interval = max(1, min(1440, int(interval or 60)))
        datetime.strptime(daily_time or "09:00", "%H:%M")
        with self._lock:
            self._mode, self._interval, self._daily_time = mode, interval, daily_time
            self._active = True
            self._next_run = self._calculate_next()
        settings = store.load_settings()
        settings.update(scanTimerMode=mode, scanIntervalMinutes=interval, scanDailyTime=daily_time)
        store.save_settings(settings)
        label = (f"每 {interval} 分钟" if mode == "interval" else f"每天 {daily_time}")
        self.events.emit("email", f"定时同步已启动：{label}", type="email_schedule")
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._active = False
            self._next_run = None
        self.events.emit("email", "定时同步已停止", type="email_schedule")
        return self.status()

    def status(self) -> dict:
        with self._lock:
            return {"active": self._active, "mode": self._mode, "interval": self._interval,
                    "dailyTime": self._daily_time,
                    "nextRun": self._next_run.strftime("%Y-%m-%d %H:%M:%S") if self._next_run else ""}

    def shutdown(self):
        self._stop.set()

    def _calculate_next(self):
        now = datetime.now()
        if self._mode == "interval":
            return now + timedelta(minutes=self._interval)
        hh, mm = map(int, self._daily_time.split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return target if target > now else target + timedelta(days=1)

    def _loop(self):
        while not self._stop.wait(1):
            fire = False
            with self._lock:
                if self._active and self._next_run and datetime.now() >= self._next_run:
                    fire = True
                    self._next_run = self._calculate_next()
            if fire:
                try:
                    self.runtime.start(None, False, True, "定时同步")
                except Exception as exc:
                    self.events.emit("email", f"定时同步跳过：{exc}", type="email_log")


class WelinkRuntime:
    """Owns history caches and independent per-conversation mining jobs."""

    def __init__(self, events: EventStream):
        self.events = events
        self._cache: dict[str, list[dict]] = {}
        self._cache_lock = threading.Lock()
        self._task_lock = threading.Lock()
        self._task = self._idle_task()
        self._cancel = threading.Event()

    @staticmethod
    def _idle_task():
        return {"running": False, "verb": "", "current": 0, "total": 0,
                "success": 0, "failed": 0, "cancelled": False, "source": ""}

    def status(self) -> dict:
        with self._task_lock:
            return dict(self._task)

    def _set_task(self, **changes):
        with self._task_lock:
            self._task.update(changes)

    def list_history(self, source: dict, start_ms: int = 0, end_ms: int = 0) -> list[dict]:
        key = welink_history.source_key(source)

        def progress(page, count, total):
            self.events.emit(
                "welink", f"正在获取 {source.get('source_name') or source.get('source_id')}："
                f"第 {page} 页，已读取 {count} 条",
                type="welink_fetch", sourceKey=key, page=page, count=count, total=total,
            )

        items = welink_history.fetch_history(source, start_ms, end_ms, progress)
        with self._cache_lock:
            self._cache[key] = items
        return [{k: v for k, v in item.items() if k != "raw"} for item in items]

    def start(self, jobs: list[dict], verb: str = "处理选中",
              scheduled: bool = False, range_mode: str = "incremental",
              cursors: dict | None = None, cursor_callback=None) -> dict:
        if not jobs:
            raise ValueError("未选择聊天来源或聊天记录")
        with self._task_lock:
            if self._task["running"]:
                raise RuntimeError("已有聊天记录处理任务正在执行")
            self._task = {"running": True, "verb": verb, "current": 0, "total": len(jobs),
                          "success": 0, "failed": 0, "cancelled": False, "source": ""}
            self._cancel.clear()
        threading.Thread(
            target=self._run,
            args=(jobs, verb, scheduled, range_mode, cursors or {}, cursor_callback),
            daemon=True,
        ).start()
        return self.status()

    def cancel(self) -> dict:
        self._cancel.set()
        return self.status()

    def _run(self, jobs, verb, scheduled, range_mode, cursors, cursor_callback):
        success = failed = 0
        try:
            settings = store.load_settings()
            backend.set_base(settings.get("backendUrl", ""))
            for index, job in enumerate(jobs, 1):
                if self._cancel.is_set():
                    break
                source = job.get("source") or {}
                key = welink_history.source_key(source)
                name = source.get("source_name") or source.get("source_id") or key
                self._set_task(current=index - 1, source=name)
                try:
                    if scheduled:
                        end_ms = int(time.time() * 1000)
                        start_ms = 0 if range_mode == "full" else int(cursors.get(key) or end_ms)
                        messages = welink_history.fetch_history(source, start_ms, end_ms)
                    else:
                        ids = {str(value) for value in job.get("messageIds") or []}
                        with self._cache_lock:
                            cached = list(self._cache.get(key) or [])
                        messages = [item for item in cached if item["id"] in ids]
                        end_ms = max((item["timestamp"] for item in messages), default=0)
                    if not messages:
                        self.events.emit("welink", f"[{name}] 没有需要处理的聊天记录",
                                         type="welink_progress", sourceKey=key)
                        if scheduled and cursor_callback:
                            cursor_callback(key, end_ms)
                        success += 1
                        continue
                    self._process_source(source, messages, settings, verb)
                    success += 1
                    if scheduled and cursor_callback:
                        cursor_callback(key, end_ms)
                    self.events.emit("welink", f"[{name}] 已提交 {len(messages)} 条聊天记录",
                                     type="welink_progress", sourceKey=key)
                except Exception as exc:
                    failed += 1
                    logging.getLogger("welink").exception("聊天记录处理失败：%s", name)
                    self.events.emit("welink", f"[{name}] 处理失败：{exc}",
                                     type="welink_progress", sourceKey=key, error=True)
                finally:
                    self._set_task(current=index, success=success, failed=failed)
            cancelled = self._cancel.is_set()
            self._set_task(cancelled=cancelled)
            text = (f"{verb}已停止" if cancelled else f"{verb}完成") + f"：成功 {success}，失败 {failed}"
            self.events.emit("welink", text, type="welink_complete",
                             success=success, failed=failed, cancelled=cancelled)
        finally:
            self._set_task(running=False, source="")

    @staticmethod
    def _process_source(source: dict, messages: list[dict], settings: dict, verb: str):
        name = source.get("source_name") or source.get("source_id") or "聊天记录"
        raw_messages = [dict(item["raw"]) for item in messages]
        raw_messages.sort(key=lambda item: int(item.get("serverSendTime") or 0))
        backend_url = settings.get("backendUrl", "")
        if not backend.is_offline_url(backend_url):
            welink_history.enrich_images_inplace(
                raw_messages, backend_url.rstrip("/"),
                lambda text: logging.getLogger("welink").warning("%s", text),
            )
        html_body = welink_history.messages_to_html(raw_messages)
        markdown = html2md(html_body)
        start_ms = int(raw_messages[0].get("serverSendTime") or 0)
        end_ms = int(raw_messages[-1].get("serverSendTime") or 0)
        digest = hashlib.sha1(
            ",".join(str(item.get("msgId") or "") for item in raw_messages).encode("utf-8")
        ).hexdigest()[:12]
        key = welink_history.source_key(source).replace(":", "_")
        chat_id = f"{key}_{start_ms}_{end_ms}_{digest}"
        if backend.is_offline_url(backend_url):
            stamp = datetime.fromtimestamp(start_ms / 1000).strftime("%Y%m%d_%H%M") if start_ms else ""
            local_archive.save_email(settings.get("outputDir", ""), f"{name}_{stamp}", html_body, markdown)
            return
        result = backend.receive_welink_chatlog({
            "ChatId": chat_id,
            "GroupId": str(source.get("source_id") or ""),
            "GroupName": name,
            "SourceType": source.get("type", "group"),
            "StartTime": start_ms,
            "EndTime": end_ms,
            "HtmlBody": html_body,
            "MarkdownBody": markdown,
            "UploadBy": settings.get("userId", ""),
            "IsDaily": False,
            "ProcessMode": verb,
        })
        if not result.get("Success", False):
            raise RuntimeError(result.get("Message") or "服务端拒绝聊天记录")


class WelinkScheduler:
    def __init__(self, runtime: WelinkRuntime, events: EventStream):
        self.runtime = runtime
        self.events = events
        self._active = False
        self._mode = "interval"
        self._interval = 60
        self._daily_time = "02:00"
        self._range_mode = "incremental"
        self._sources: list[dict] = []
        self._cursors: dict[str, int] = {}
        self._next_run = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def start(self, sources: list[dict], mode: str, interval: int,
              daily_time: str, range_mode: str) -> dict:
        if not sources:
            raise ValueError("请至少勾选一个群组或用户")
        mode = "daily" if mode == "daily" else "interval"
        range_mode = "full" if range_mode == "full" else "incremental"
        interval = max(1, min(1440, int(interval or 60)))
        datetime.strptime(daily_time or "02:00", "%H:%M")
        settings = store.load_settings()
        cursors = settings.get("welinkScheduleCursors") or {}
        now_ms = int(time.time() * 1000)
        if range_mode == "incremental":
            for source in sources:
                cursors.setdefault(welink_history.source_key(source), now_ms)
        with self._lock:
            self._sources = [dict(source) for source in sources]
            self._mode, self._interval = mode, interval
            self._daily_time, self._range_mode = daily_time, range_mode
            self._cursors = cursors
            self._active = True
            self._next_run = self._calculate_next()
        settings.update(
            welinkScheduleMode=mode,
            welinkScheduleInterval=interval,
            welinkScheduleDailyTime=daily_time,
            welinkScheduleRangeMode=range_mode,
            welinkScheduleSources=[welink_history.source_key(source) for source in sources],
            welinkScheduleCursors=cursors,
        )
        store.save_settings(settings)
        self.events.emit("welink", "聊天记录定时处理已启动", type="welink_schedule")
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._active = False
            self._next_run = None
        self.events.emit("welink", "聊天记录定时处理已停止", type="welink_schedule")
        return self.status()

    def status(self) -> dict:
        with self._lock:
            return {"active": self._active, "mode": self._mode, "interval": self._interval,
                    "dailyTime": self._daily_time, "rangeMode": self._range_mode,
                    "sourceCount": len(self._sources),
                    "nextRun": self._next_run.strftime("%Y-%m-%d %H:%M:%S") if self._next_run else ""}

    def shutdown(self):
        self._stop.set()

    def _calculate_next(self):
        now = datetime.now()
        if self._mode == "interval":
            return now + timedelta(minutes=self._interval)
        hh, mm = map(int, self._daily_time.split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return target if target > now else target + timedelta(days=1)

    def _save_cursor(self, key: str, value: int):
        with self._lock:
            self._cursors[key] = value
            cursors = dict(self._cursors)
        settings = store.load_settings()
        settings["welinkScheduleCursors"] = cursors
        store.save_settings(settings)

    def _loop(self):
        while not self._stop.wait(1):
            with self._lock:
                fire = bool(self._active and self._next_run and datetime.now() >= self._next_run)
                if fire:
                    self._next_run = self._calculate_next()
                    sources = [dict(source) for source in self._sources]
                    range_mode = self._range_mode
                    cursors = dict(self._cursors)
            if not fire:
                continue
            try:
                jobs = [{"source": source} for source in sources]
                self.runtime.start(jobs, "定时处理", True, range_mode, cursors, self._save_cursor)
            except Exception as exc:
                self.events.emit("welink", f"定时处理跳过：{exc}", type="welink_schedule")
