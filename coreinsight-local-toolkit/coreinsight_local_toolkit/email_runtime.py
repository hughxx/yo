from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime

from .email_store import EmailConfigStore
from .models import EmailConfig, EmailExtractRequest, EmailRule, EmailScheduleSetRequest
from .outlook import OutlookClient
from .processor import ExtractionCancelled, LocalExperienceProcessor
from .scheduler import _parse_time, next_cron
from .time_format import format_datetime, parse_datetime


logger = logging.getLogger(__name__)
DOCUMENT_CHUNK_SIZE = 36_000
EMAIL_LIST_SCAN_LIMIT = 10_000


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
        self.scan_task = self._scan_idle()
        self.cache_path = self.store.path.with_name("email_cache.json")
        self._thread = None
        self._scan_thread = None

    @staticmethod
    def _idle() -> dict:
        return {"running": False, "taskId": "", "status": "idle", "scanned": 0,
                "selected": 0, "processed": 0, "message": "", "error": "",
                "docId": "", "docIds": [], "title": "", "scheduled": False}

    @staticmethod
    def _scan_idle() -> dict:
        return {"running": False, "taskId": "", "status": "idle",
                "scanned": 0, "total": 0, "items": [], "incremental": False,
                "message": "", "error": ""}

    def scan_status(self, include_items: bool = False) -> dict:
        with self.lock:
            value = dict(self.scan_task)
        if not include_items:
            value.pop("items", None)
        return value

    def _scan_set(self, **changes):
        with self.lock:
            self.scan_task.update(changes)

    def _read_cache(self) -> dict:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _write_cache(self, folders: list[str], items: list[dict]):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "folders": folders, "items": items,
            "updatedAt": format_datetime(datetime.now().astimezone()),
        }, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.cache_path)

    def start_scan(self, folders: list[str], force_full: bool = False) -> dict:
        requested = list(dict.fromkeys(str(item).strip() for item in folders
                                      if str(item).strip()))
        with self.lock:
            if self.scan_task.get("running"):
                raise RuntimeError("邮件列表正在扫描中")
            cache = self._read_cache()
            cached_folders = cache.get("folders") or []
            incremental = bool(cache.get("items")) and not force_full \
                and cached_folders == requested
            task_id = uuid.uuid4().hex
            self.scan_task = {**self._scan_idle(), "running": True,
                              "taskId": task_id, "status": "scanning",
                              "incremental": incremental,
                              "message": "正在增量读取邮件" if incremental
                              else "正在全量读取邮件"}
            if not requested:
                self.scan_task.update(
                    running=False, status="done", scanned=0, total=0,
                    items=[], message="未选择文件夹")
                self._write_cache([], [])
                return self.scan_status()
        self._scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(requested, force_full, cache, incremental), daemon=True)
        self._scan_thread.start()
        return self.scan_status()

    def _scan_worker(self, folders, force_full, cache, incremental):
        try:
            cached_items = cache.get("items") or []
            start_ms = 0
            if incremental and cached_items:
                newest = max(int(item.get("timestamp") or 0)
                             for item in cached_items)
                start_ms = max(0, newest - 1000)
            def progress(scanned, total=0):
                self._scan_set(scanned=scanned, total=max(total, scanned),
                               message=("正在增量读取邮件" if incremental
                                        else "正在全量读取邮件") +
                                       f"：已读取 {scanned} 封")
            # A background scan is genuinely full-range; the bounded legacy
            # page endpoint remains separate for compatibility.
            rows = self.outlook.list_messages(
                folders, start_ms, 0, 0,
                progress=progress)
            if incremental:
                merged = {str(item.get("id")): item for item in cached_items}
                merged.update({str(item.get("id")): item for item in rows})
                rows = list(merged.values())
                rows.sort(key=lambda item: (int(item.get("timestamp") or 0),
                                            str(item.get("id") or "")),
                          reverse=True)
            self._write_cache(folders, rows)
            self._scan_set(status="done", running=False, scanned=len(rows),
                           total=len(rows), items=rows,
                           message=("增量读取完成" if incremental else "全量读取完成"))
        except Exception as exc:
            logger.exception("email scan failed")
            self._scan_set(status="failed", running=False, error=str(exc),
                           message="邮件扫描失败")

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

    def list_messages(self, folders: list[str], start_ms: int, end_ms: int,
                      query: str = "", matched_only: bool = False,
                      maximum: int = EMAIL_LIST_SCAN_LIMIT,
                      outlook_body_search: bool = True) -> list[dict]:
        config = self.store.get()
        paths = folders or config.folders
        rows = self.outlook.list_messages(paths, start_ms, end_ms, maximum)
        return self._filter_messages(
            rows, paths, config, query, matched_only, outlook_body_search)

    def list_message_page(self, folders: list[str], start_ms: int, end_ms: int,
                          query: str, matched_only: bool,
                          offset: int, limit: int) -> dict:
        """Read only enough Outlook summaries to satisfy the requested page.

        Outlook does not expose a stable cross-folder offset cursor.  Reading the
        first ``offset + limit + 1`` rows from each sorted folder and globally
        merging them yields a correct page without materialising the mailbox.
        Filtered searches grow the scan window until the page is full or the
        configured safety limit is reached.
        """
        target = offset + limit + 1
        filtered_search = bool(query.strip() or matched_only)
        scan_limit = min(
            EMAIL_LIST_SCAN_LIMIT,
            max(target, 200 if filtered_search else target))
        paths = folders or self.store.get().folders
        config = self.store.get()

        # Once the background scan has completed, serve the persisted summary
        # cache instead of opening Outlook for every page click.
        cached = self._read_cache()
        if cached.get("items") and (cached.get("folders") or []) == paths:
            rows = cached["items"]
            filtered = self._filter_messages(
                rows, paths, config, query, matched_only,
                outlook_body_search=False)
            page = filtered[offset:offset + limit]
            return {"items": page, "total": len(filtered),
                    "totalExact": True, "offset": offset, "limit": limit,
                    "hasMore": offset + limit < len(filtered),
                    "scanned": len(rows), "source": "cache"}

        while True:
            rows = self.outlook.list_messages(paths, start_ms, end_ms, scan_limit)
            source_exhausted = len(rows) < scan_limit
            filtered = self._filter_messages(
                rows, paths, config, query, matched_only,
                outlook_body_search=False)
            if (len(filtered) >= target or source_exhausted
                    or scan_limit >= EMAIL_LIST_SCAN_LIMIT):
                break
            scan_limit = min(EMAIL_LIST_SCAN_LIMIT, scan_limit * 2)

        total_exact = source_exhausted
        has_more = len(filtered) > offset + limit
        if not has_more and not total_exact and scan_limit >= EMAIL_LIST_SCAN_LIMIT:
            # The 10k safety cap is not proof that the mailbox has ended.  Keep
            # hasMore truthful as a lower-bound hint for very large mailboxes.
            has_more = len(filtered) >= offset + limit
        page = filtered[offset:offset + limit]
        total = len(filtered) if total_exact else max(
            len(filtered), offset + len(page) + (1 if has_more else 0))
        return {"items": page, "total": total, "totalExact": total_exact,
                "offset": offset, "limit": limit, "hasMore": has_more,
                "scanned": len(rows)}

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
        self.processor.validate(upload_by, payload.skillId, payload.extractMode)
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
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
        scan_thread = self._scan_thread
        if scan_thread and scan_thread is not threading.current_thread():
            scan_thread.join(timeout=5)

    def _run(self, payload, start_ms, end_ms, scheduled, on_complete, upload_by):
        success = False
        result = {}
        try:
            rows = None
            # Manual extraction is launched from the already displayed scan
            # snapshot.  Do not reopen Outlook and scan the mailbox again.
            if not scheduled:
                cached = self._read_cache()
                cached_folders = cached.get("folders") or []
                requested_folders = list(payload.folders or [])
                if cached.get("items") and cached_folders == requested_folders:
                    rows = self._filter_messages(
                        list(cached["items"]), requested_folders,
                        self.store.get(), payload.query,
                        payload.matchedOnly, outlook_body_search=False)
                    rows = [row for row in rows
                            if (not start_ms or int(row.get("timestamp") or 0) >= start_ms)
                            and (not end_ms or int(row.get("timestamp") or 0) <= end_ms)]
            if rows is None:
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
                documents, payload.skillId, upload_by, self.task["taskId"],
                progress, self.cancel_event, group_id="outlook-mailbox",
                scheduled=scheduled, extract_mode=payload.extractMode,
                source_type="email")
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
            self._finish("cancelled", "邮件提取任务已取消", {})
        except Exception as exc:
            logger.exception("email extraction failed")
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
            payload.uploadBy, payload.skillId, payload.extractMode)
        _parse_time(payload.scheduleTime)
        config.folders = payload.folders or config.folders
        config.uploadBy = payload.uploadBy.strip()
        config.skillId = payload.skillId
        config.extractMode = payload.extractMode
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
            skillId=config.skillId, extractMode=config.extractMode,
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
