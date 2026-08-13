from __future__ import annotations

import logging
import threading
import uuid

from .models import ExtractRequest
from .processor import ExtractionCancelled, LocalExperienceProcessor
from .store import GroupStore
from .welink import WelinkHistory


logger = logging.getLogger(__name__)


class ExtractionRuntime:
    def __init__(self, history: WelinkHistory, groups: GroupStore,
                 processor: LocalExperienceProcessor, default_upload_by: str = ""):
        self.history = history
        self.groups = groups
        self.processor = processor
        self.default_upload_by = default_upload_by
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._task = self._idle()

    @staticmethod
    def _idle() -> dict:
        return {"running": False, "taskId": "", "status": "idle", "scanned": 0,
                "selected": 0, "message": "", "error": "", "docId": "", "title": ""}

    def status(self) -> dict:
        with self._lock: return dict(self._task)

    def _set(self, **changes) -> None:
        with self._lock: self._task.update(changes)

    def start(self, payload: ExtractRequest, start_ms: int, end_ms: int,
              scheduled: bool = False, on_complete=None) -> dict:
        if payload.extractMode == "draft":
            raise ValueError("草稿审核尚未实现，请先选择直接入库")
        group = self.groups.get(payload.groupId)
        if not group: raise ValueError("请先绑定该群组")
        upload_by = payload.uploadBy.strip() or self.default_upload_by
        self.processor.validate(upload_by, payload.skillId)
        with self._lock:
            if self._task.get("running"): raise RuntimeError("已有聊天记录提取任务正在执行")
            task_id = uuid.uuid4().hex
            self._task = {"running": True, "taskId": task_id, "status": "fetching",
                          "groupId": payload.groupId, "scheduled": scheduled,
                          "scanned": 0, "selected": 0, "message": "正在本地读取并筛选 WeLink 消息",
                          "error": "", "docId": "", "title": ""}
            self._cancel.clear()
        self.groups.set_status(payload.groupId, "extracting")
        logger.info(
            "extraction started task_id=%s group_id=%s scheduled=%s range=%d..%d skill=%s",
            task_id, payload.groupId, scheduled, start_ms, end_ms, payload.skillId)
        threading.Thread(
            target=self._run,
            args=(payload, start_ms, end_ms, task_id, upload_by, scheduled, on_complete),
            daemon=True,
        ).start()
        return self.status()

    def cancel(self) -> dict:
        with self._lock:
            if not self._task.get("running"):
                return dict(self._task)
        self._cancel.set(); self._set(message="正在取消（当前网络请求返回后停止）"); return self.status()

    def _run(self, payload: ExtractRequest, start_ms: int, end_ms: int,
             task_id: str, upload_by: str, scheduled: bool, on_complete) -> None:
        excluded = {str(value) for value in payload.selection.excludedMessageIds}
        explicit = {str(value) for value in payload.selection.selectedMessageIds}
        cursor = ""; seen_cursors = set(); messages = []; scanned = 0
        try:
            while True:
                if self._cancel.is_set():
                    self._cancelled(payload.groupId); return
                page = self.history.fetch_page(payload.groupId, start_ms, end_ms, cursor, 100)
                scanned += len(page["items"])
                for item in page["items"]:
                    message_id = str(item["id"])
                    include = message_id not in excluded if payload.selection.mode == "all" else message_id in explicit
                    if include: messages.append(item)
                self._set(scanned=scanned, selected=len(messages), message=f"本地已扫描 {scanned} 条，选中 {len(messages)} 条")
                next_cursor = page["nextCursor"]
                if payload.selection.mode == "explicit" and explicit and len(messages) >= len(explicit): break
                if not page["hasMore"] or not next_cursor or next_cursor in seen_cursors: break
                seen_cursors.add(next_cursor); cursor = next_cursor
            logger.info(
                "messages fetched task_id=%s scanned=%d selected=%d",
                task_id, scanned, len(messages))
            if not messages and scheduled:
                self._restore_group_status(payload.groupId)
                if on_complete: on_complete(True, end_ms, {})
                self._set(running=False, status="done", message="本次没有新增消息")
                logger.info("scheduled extraction empty task_id=%s", task_id)
                return
            if not messages: raise RuntimeError("所选范围内没有可提取的消息")
            if self._cancel.is_set():
                self._cancelled(payload.groupId); return
            def progress(status, message): self._set(status=status, message=message)
            result = self.processor.process(
                messages, payload.skillId, upload_by, task_id, progress, self._cancel,
                group_id=payload.groupId, scheduled=scheduled)
            self._restore_group_status(payload.groupId)
            if on_complete: on_complete(True, end_ms, result)
            self._set(running=False, status="done", message="经验提取并入库完成", **result)
            logger.info(
                "extraction completed task_id=%s run_id=%s experiences=%s",
                task_id, result.get("remoteRunId", ""), result.get("experienceCount", 0))
        except ExtractionCancelled:
            logger.info("extraction cancelled task_id=%s", task_id)
            self._cancelled(payload.groupId)
        except Exception as exc:
            logger.exception("extraction failed task_id=%s group_id=%s", task_id, payload.groupId)
            self._restore_group_status(payload.groupId)
            if on_complete: on_complete(False, end_ms, {"error": str(exc)})
            self._set(running=False, status="failed", error=str(exc), message="提取任务失败")

    def _restore_group_status(self, group_id: str) -> None:
        group = self.groups.get(group_id)
        if group:
            self.groups.set_status(group_id, "scheduled" if group.scheduleEnabled else "idle")

    def _cancelled(self, group_id: str) -> None:
        self._restore_group_status(group_id)
        self._set(running=False, status="cancelled", message="任务已取消")
