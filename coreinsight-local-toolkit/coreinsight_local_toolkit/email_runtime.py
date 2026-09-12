from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import datetime

from .email_store import EmailConfigStore
from .models import (
    EmailConfig, EmailExtractRequest, EmailListRequest, EmailRule,
    EmailScheduleSetRequest,
)
from .outlook import OutlookClient
from .processor import ExtractionCancelled, LocalExperienceProcessor
from .scheduler import _parse_time, next_cron
from .time_format import format_datetime, parse_datetime


logger = logging.getLogger(__name__)
DOCUMENT_CHUNK_SIZE = 36_000
EMAIL_EXTRACT_SCAN_LIMIT = 10_000


def _active_filter_rules(config: EmailConfig) -> list[EmailRule]:
    """Only enabled rules with at least one real condition are privacy filters."""
    return [rule for rule in config.rules if rule.enabled and (
        rule.subjectKeywords or rule.bodyKeywords or rule.senders)]


def _rule_match(row: dict, rule: EmailRule, body: str = "",
                body_hit: bool | None = None) -> bool:
    if not rule.enabled:
        return False
    checks = []
    if rule.subjectKeywords:
        folded = str(row.get("subject") or "").casefold()
        checks.append(any(keyword.casefold() in folded
                          for keyword in rule.subjectKeywords))
    if rule.bodyKeywords:
        if body_hit is None:
            folded = body.casefold()
            body_hit = any(keyword.casefold() in folded
                           for keyword in rule.bodyKeywords)
        checks.append(body_hit)
    if rule.senders:
        folded = " ".join((str(row.get("senderName") or ""),
                            str(row.get("senderEmail") or ""))).casefold()
        checks.append(any(keyword.casefold() in folded
                          for keyword in rule.senders))
    if not checks:
        return False
    return all(checks) if rule.logic == "AND" else any(checks)


def _split_markdown(content: str, maximum: int = DOCUMENT_CHUNK_SIZE) -> list[str]:
    if len(content) <= maximum:
        return [content]
    sections = re.split(r"(?=\n#{1,3} )|\n\n", content)
    chunks, current = [], ""
    for section in sections:
        separator = "\n\n" if current else ""
        if current and len(current) + len(separator) + len(section) > maximum:
            chunks.append(current)
            current = ""
        while len(section) > maximum:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(section[:maximum])
            section = section[maximum:]
        current += ("\n\n" if current else "") + section
    if current:
        chunks.append(current)
    return chunks


class EmailRuntime:
    def __init__(self, outlook: OutlookClient, store: EmailConfigStore,
                 processor: LocalExperienceProcessor, notifier=None,
                 default_upload_by: str = ""):
        self.outlook = outlook
        self.store = store
        self.processor = processor
        self.notifier = notifier
        self.default_upload_by = default_upload_by
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.task = self._idle()
        self.history: list[dict] = []
        self.list_task = self._list_idle()
        self._thread = None
        self._list_thread = None
        self._list_cancel_event = threading.Event()

    @staticmethod
    def _idle() -> dict:
        return {"running": False, "taskId": "", "status": "idle", "scanned": 0,
                "selected": 0, "processed": 0, "message": "", "error": "",
                "docId": "", "docIds": [], "title": "", "scheduled": False,
                "itemStatuses": {}}

    @staticmethod
    def _list_idle() -> dict:
        return {"running": False, "taskId": "", "status": "idle",
                "scanned": 0, "total": 0, "items": [],
                "message": "", "error": ""}

    def list_status(self, task_id: str = "") -> dict | None:
        with self.lock:
            if task_id and self.list_task.get("taskId") != task_id:
                return None
            return dict(self.list_task)

    def _list_set(self, task_id: str, **changes) -> bool:
        with self.lock:
            if self.list_task.get("taskId") != task_id:
                return False
            self.list_task.update(changes)
            return True

    def start_list(self, payload: EmailListRequest,
                   start_ms: int, end_ms: int) -> dict:
        folders = list(payload.folders)
        with self.lock:
            if self.list_task.get("running"):
                self._list_cancel_event.set()
            task_id = uuid.uuid4().hex
            cancel_event = threading.Event()
            self._list_cancel_event = cancel_event
            self.list_task = {**self._list_idle(), "running": True,
                              "taskId": task_id, "status": "loading",
                              "folders": folders,
                              "message": "正在读取 Outlook 邮件"}
        self._list_thread = threading.Thread(
            target=self._list_worker,
            args=(task_id, payload, start_ms, end_ms, cancel_event),
            daemon=True)
        self._list_thread.start()
        return self.list_status(task_id) or self._list_idle()

    def _list_worker(self, task_id: str, payload: EmailListRequest,
                     start_ms: int, end_ms: int,
                     cancel_event: threading.Event) -> None:
        try:
            def progress(scanned, total=0):
                self._list_set(
                    task_id, scanned=scanned, total=max(total, scanned),
                    message=f"正在读取 Outlook 邮件：已读取 {scanned} 封")

            rows = self.outlook.list_messages(
                payload.folders, start_ms, end_ms, 0,
                progress=progress, cancelled=cancel_event.is_set)
            if cancel_event.is_set():
                return
            self._list_set(task_id, status="filtering", scanned=len(rows),
                           total=len(rows), message="正在应用邮件筛选条件")
            rows = self._filter_messages(
                rows, payload.folders, self.store.get(), payload.query,
                payload.matchedOnly, outlook_body_search=True)
            if cancel_event.is_set():
                return
            self._list_set(task_id, status="done", running=False,
                           scanned=len(rows), total=len(rows), items=rows,
                           message=f"已读取 {len(rows)} 封邮件")
        except Exception as exc:
            if cancel_event.is_set():
                return
            logger.exception("email list failed")
            self._list_set(task_id, status="failed", running=False,
                           error=str(exc), message="邮件列表读取失败")

    def status(self) -> dict:
        with self.lock:
            return dict(self.task)

    def tasks(self) -> list[dict]:
        with self.lock:
            current_id = self.task.get("taskId")
            rows = ([dict(self.task)] if current_id else []) + [
                dict(row) for row in reversed(self.history)
                if row.get("taskId") != current_id]
            return rows[:100]

    def _set(self, **changes):
        with self.lock:
            self.task.update(changes)

    def _set_item_status(self, item_id: str, status: str, error: str = ""):
        with self.lock:
            statuses = dict(self.task.get("itemStatuses") or {})
            value = {"itemId": str(item_id), "status": status}
            if error:
                value["error"] = error
            statuses[str(item_id)] = value
            self.task["itemStatuses"] = statuses

    def list_messages(self, folders: list[str], start_ms: int, end_ms: int,
                      query: str = "", matched_only: bool = False,
                      maximum: int = EMAIL_EXTRACT_SCAN_LIMIT,
                      outlook_body_search: bool = True) -> list[dict]:
        config = self.store.get()
        paths = folders or config.folders
        rows = self.outlook.list_messages(paths, start_ms, end_ms, maximum)
        return self._filter_messages(
            rows, paths, config, query, matched_only, outlook_body_search)

    def _filter_messages(self, rows: list[dict], paths: list[str],
                         config: EmailConfig, query: str,
                         matched_only: bool,
                         outlook_body_search: bool) -> list[dict]:
        rules = [*config.rules, *config.blacklist]
        body_rules = [rule for rule in rules if rule.enabled and rule.bodyKeywords]
        query_folded = query.strip().casefold()
        body_matches = {}
        query_body_matches = set()
        bodies = {}
        if (body_rules or query_folded) and outlook_body_search:
            try:
                keyword_sets = [rule.bodyKeywords for rule in body_rules]
                if query_folded:
                    keyword_sets.append([query.strip()])
                matches = self.outlook.search_body_matches(
                    paths, keyword_sets)
                # Outlook's DASL body index can return an empty result for CJK
                # terms without raising a COM error.  Verify those apparent
                # misses against the bodies of the already bounded list rows.
                # The normal indexed path remains unchanged for ASCII terms
                # and for CJK searches that produced candidate hits.
                candidate_ids = {
                    str(row.get("id") or "") for row in rows
                    if row.get("id")
                }
                verify_indexes = [
                    index for index, keywords in enumerate(keyword_sets)
                    if any(not keyword.isascii() for keyword in keywords)
                    and not (matches[index] & candidate_ids)
                ]
                if verify_indexes:
                    bodies = self.outlook.body_texts(list(candidate_ids))
                    folded_bodies = {
                        item_id: body.casefold()
                        for item_id, body in bodies.items()
                    }
                    for index in verify_indexes:
                        folded_keywords = [
                            keyword.casefold() for keyword in keyword_sets[index]
                        ]
                        matches[index].update(
                            item_id for item_id, body in folded_bodies.items()
                            if any(keyword in body for keyword in folded_keywords)
                        )
                body_matches = {rule.id or str(id(rule)): values
                                for rule, values in zip(body_rules, matches[:len(body_rules)])}
                if query_folded:
                    query_body_matches = matches[-1]
            except Exception:
                logger.warning("falling back to local Outlook body matching",
                               exc_info=True)
                body_ids = [row["id"] for row in rows]
                bodies = self.outlook.body_texts(body_ids)
        elif body_rules or query_folded:
            # A paged preview only needs bodies for the bounded candidate window;
            # asking Outlook to search the whole mailbox defeats pagination.
            body_ids = [row["id"] for row in rows]
            bodies = self.outlook.body_texts(body_ids)
        result = []
        for row in rows:
            body = bodies.get(row["id"], "")
            def matches(rule):
                key = rule.id or str(id(rule))
                hit = row["id"] in body_matches.get(key, set()) \
                    if rule.bodyKeywords and body_matches else None
                return _rule_match(row, rule, body, hit)
            allowed = next((rule.name for rule in config.rules
                            if matches(rule)), "")
            blocked = next((rule.name for rule in config.blacklist
                            if matches(rule)), "")
            row = {**row, "matchedRule": allowed if allowed and not blocked else "",
                   "blockedRule": blocked}
            if matched_only and not row["matchedRule"]:
                continue
            if (query_folded and row["id"] not in query_body_matches
                    and query_folded not in " ".join((
                    row["subject"], row["senderName"], row["senderEmail"],
                    row["conversationTopic"], body)).casefold()):
                continue
            result.append(row)
        return result

    def start(self, payload: EmailExtractRequest, start_ms: int, end_ms: int,
              scheduled: bool = False, on_complete=None) -> dict:
        upload_by = payload.uploadBy.strip() or self.default_upload_by
        self.processor.validate(upload_by, payload.resource, payload.extractMode)
        with self.lock:
            if self.task.get("running"):
                raise RuntimeError("已有邮件提取任务正在执行")
            task_id = uuid.uuid4().hex
            self.task = {**self._idle(), "running": True, "taskId": task_id,
                         "status": "fetching", "scheduled": scheduled,
                         "message": "正在读取 Outlook 邮件"}
            self.cancel_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(payload, start_ms, end_ms, scheduled, on_complete, upload_by),
            daemon=True)
        self._thread.start()
        return self.status()

    def cancel(self) -> dict:
        with self.lock:
            if self.task.get("running"):
                self.cancel_event.set()
                self.task["message"] = "正在取消（当前 Outlook 或网络操作结束后停止）"
            return dict(self.task)

    def close(self):
        self.cancel_event.set()
        self._list_cancel_event.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
        list_thread = self._list_thread
        if list_thread and list_thread is not threading.current_thread():
            list_thread.join(timeout=5)

    def _run(self, payload, start_ms, end_ms, scheduled, on_complete, upload_by):
        success = False
        result = {}
        current_item_id = ""
        try:
            rows = self.list_messages(
                payload.folders, start_ms, end_ms, payload.query,
                payload.matchedOnly)
            if scheduled and start_ms:
                rows = [row for row in rows
                        if int(row.get("timestamp") or 0) > start_ms]
            self._set(scanned=len(rows))
            excluded = {str(value) for value in payload.selection.excludedItemIds}
            selected_ids = {str(value) for value in payload.selection.selectedItemIds}
            if payload.selection.mode == "all":
                selected = [row for row in rows if row["id"] not in excluded]
            else:
                selected = [row for row in rows if row["id"] in selected_ids]
            self._set(selected=len(selected), message=f"已选择 {len(selected)} 封邮件")
            with self.lock:
                self.task["itemStatuses"] = {
                    str(row["id"]): {"itemId": str(row["id"]), "status": "queued"}
                    for row in selected
                }
            if not selected:
                if scheduled:
                    success = True
                    self._finish("done", "本次没有新增且符合条件的邮件", {})
                    return
                raise RuntimeError("当前条件下没有可提取的邮件")
            documents = []
            for index, row in enumerate(reversed(selected), 1):
                if self.cancel_event.is_set():
                    raise ExtractionCancelled("任务已取消")
                current_item_id = str(row["id"])
                self._set_item_status(current_item_id, "processing")
                self._set(status="workspace", processed=index - 1,
                          message=f"正在转换邮件与附件 {index}/{len(selected)}")
                detail = self.outlook.get_message(row["id"], True)
                for part, markdown in enumerate(_split_markdown(detail["markdown"]), 1):
                    documents.append({
                        "id": f"{row['id']}-{part}",
                        "sender": row.get("senderName", ""),
                        "timestamp": int(row.get("timestamp") or 0) + part - 1,
                        "rawContent": markdown,
                        "preformattedMarkdown": True,
                    })
                self._set(processed=index)

            def progress(status, message):
                self._set(status=status, message=message)

            result = self.processor.process(
                documents, upload_by, self.task["taskId"],
                progress, self.cancel_event, group_id="outlook-mailbox",
                scheduled=scheduled, extract_mode=payload.extractMode,
                source_type="email", scene=payload.scene,
                scene_id=payload.scene_id, resource=payload.resource)
            for row in selected:
                self._set_item_status(str(row["id"]), "success")
            if self.notifier:
                experiences = result.get("experiences") or []
                try:
                    self.notifier.notify(upload_by, payload.extractMode,
                                         experiences, source_type="email")
                except TypeError as exc:
                    # Keep compatibility with injected notifiers from older
                    # integrations that still accept the three-argument API.
                    if "source_type" not in str(exc):
                        raise
                    self.notifier.notify(upload_by, payload.extractMode,
                                         experiences)
            success = True
            message = ("邮件经验草稿已生成，等待平台确认" if payload.extractMode == "draft"
                       else "邮件经验已提取并入库")
            self._finish("done", message, result)
        except ExtractionCancelled:
            with self.lock:
                statuses = dict(self.task.get("itemStatuses") or {})
            for item_id, item in statuses.items():
                if item.get("status") in ("queued", "processing"):
                    self._set_item_status(item_id, "cancelled")
            self._finish("cancelled", "邮件提取任务已取消", {})
        except Exception as exc:
            logger.exception("email extraction failed")
            if current_item_id:
                self._set_item_status(current_item_id, "failed", str(exc))
            self._finish("failed", "邮件提取任务失败", {"error": str(exc)})
        finally:
            if on_complete:
                try:
                    on_complete(success, end_ms, result)
                except Exception:
                    logger.exception("email schedule completion callback failed")

    def _finish(self, status: str, message: str, values: dict):
        with self.lock:
            self.task.update(values, status=status, message=message, running=False)
            if self.task.get("taskId"):
                self.history.append(dict(self.task))
                self.history = self.history[-100:]


def _next_run(config: EmailConfig, after: datetime) -> datetime:
    if config.scheduleFreq == "custom":
        return next_cron(config.scheduleCron, after)
    hour, minute, second = _parse_time(config.scheduleTime)
    if config.scheduleFreq == "daily":
        candidate = after.replace(hour=hour, minute=minute, second=second, microsecond=0)
        from datetime import timedelta
        return candidate if candidate > after else candidate + timedelta(days=1)
    if config.scheduleFreq == "weekly":
        from datetime import timedelta
        days = (config.scheduleWeekday - after.weekday()) % 7
        candidate = (after + timedelta(days=days)).replace(
            hour=hour, minute=minute, second=second, microsecond=0)
        return candidate if candidate > after else candidate + timedelta(days=7)
    import calendar
    for offset in range(14):
        year = after.year + (after.month - 1 + offset) // 12
        month = (after.month - 1 + offset) % 12 + 1
        if config.scheduleDay > calendar.monthrange(year, month)[1]:
            continue
        candidate = after.replace(
            year=year, month=month, day=config.scheduleDay,
            hour=hour, minute=minute, second=second, microsecond=0)
        if candidate > after:
            return candidate
    raise ValueError("无法计算邮件定时任务的下次执行时间")


class EmailScheduleRuntime:
    def __init__(self, store: EmailConfigStore, runtime: EmailRuntime):
        self.store = store
        self.runtime = runtime
        self.stop_event = threading.Event()
        self._recover()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def set(self, payload: EmailScheduleSetRequest, now: datetime | None = None):
        now = now or datetime.now().astimezone()
        config = self.store.get()
        if not _active_filter_rules(config):
            raise ValueError("定时增量提取必须先配置并启用至少一条有效的提取规则")
        self.runtime.processor.validate(
            payload.uploadBy, payload.resource, payload.extractMode)
        _parse_time(payload.scheduleTime)
        config.folders = payload.folders or config.folders
        config.uploadBy = payload.uploadBy.strip()
        config.extractMode = payload.extractMode
        config.resource = payload.resource
        if payload.scene:
            config.scene = payload.scene
        if payload.scene_id:
            config.scene_id = payload.scene_id
        config.scheduleFreq = payload.scheduleFreq
        config.scheduleTime = payload.scheduleTime
        config.scheduleCron = payload.scheduleCron.strip()
        config.scheduleWeekday = now.weekday()
        config.scheduleDay = now.day
        if not config.scheduleEnabled or payload.since is not None:
            initial = payload.since or format_datetime(now)
            config.scheduleSince = initial
            config.scheduleCursor = initial
        config.scheduleEnabled = True
        config.scheduleNextRun = format_datetime(_next_run(config, now))
        return self.store.save(config)

    def cancel(self):
        config = self.store.get()
        config.scheduleEnabled = False
        config.scheduleNextRun = ""
        if self.runtime.status().get("running") and self.runtime.status().get("scheduled"):
            self.runtime.cancel()
        return self.store.save(config)

    def tick(self, now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        config = self.store.get()
        if not config.scheduleEnabled or not config.scheduleNextRun:
            return False
        if not _active_filter_rules(config):
            logger.warning("email schedule disabled because no active filter rule exists")
            config.scheduleEnabled = False
            config.scheduleNextRun = ""
            self.store.save(config)
            return False
        if parse_datetime(config.scheduleNextRun) > now:
            return False
        start = parse_datetime(config.scheduleCursor or config.scheduleSince)
        payload = EmailExtractRequest(
            folders=config.folders, uploadBy=config.uploadBy,
            extractMode=config.extractMode, resource=config.resource,
            scene=config.scene, scene_id=config.scene_id,
            matchedOnly=True,
            selection={"mode": "all"})
        try:
            self.runtime.start(
                payload, int(start.timestamp() * 1000), int(now.timestamp() * 1000),
                scheduled=True,
                on_complete=lambda ok, end_ms, result: self._completed(ok, end_ms))
            return True
        except (RuntimeError, ValueError):
            return False

    def _completed(self, success: bool, end_ms: int):
        config = self.store.get()
        if not config.scheduleEnabled:
            return
        completed = datetime.fromtimestamp(end_ms / 1000).astimezone()
        if success:
            config.scheduleCursor = format_datetime(completed)
        config.scheduleNextRun = format_datetime(_next_run(config, completed))
        self.store.save(config)

    def _recover(self):
        config = self.store.get()
        if not config.scheduleEnabled:
            return
        if not _active_filter_rules(config):
            logger.warning("email schedule recovery skipped: no active filter rule")
            config.scheduleEnabled = False
            config.scheduleNextRun = ""
            self.store.save(config)
            return
        try:
            if not config.scheduleCursor:
                config.scheduleCursor = config.scheduleSince or format_datetime(
                    datetime.now().astimezone())
            if not config.scheduleNextRun:
                config.scheduleNextRun = format_datetime(
                    _next_run(config, datetime.now().astimezone()))
            self.store.save(config)
        except ValueError:
            config.scheduleEnabled = False
            config.scheduleNextRun = ""
            self.store.save(config)

    def close(self):
        self.stop_event.set()

    def _loop(self):
        while not self.stop_event.wait(15):
            try:
                self.tick()
            except Exception:
                logger.exception("email scheduler tick failed")
