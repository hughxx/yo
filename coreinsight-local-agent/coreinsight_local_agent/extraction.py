from __future__ import annotations

import threading
import uuid

from .models import ExtractRequest
from .processor import LocalExperienceProcessor
from .store import GroupStore
from .welink import WelinkHistory


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

    def start(self, payload: ExtractRequest, start_ms: int, end_ms: int) -> dict:
        if payload.extractMode == "draft":
            raise ValueError("草稿审核尚未实现，请先选择直接入库")
        group = self.groups.get(payload.groupId)
        if not group: raise ValueError("请先绑定该群组")
        upload_by = payload.uploadBy.strip() or self.default_upload_by
        self.processor.validate(upload_by)
        with self._lock:
            if self._task.get("running"): raise RuntimeError("已有聊天记录提取任务正在执行")
            task_id = uuid.uuid4().hex
            self._task = {"running": True, "taskId": task_id, "status": "fetching",
                          "scanned": 0, "selected": 0, "message": "正在本地读取并筛选 WeLink 消息",
                          "error": "", "docId": "", "title": ""}
            self._cancel.clear()
        threading.Thread(target=self._run, args=(payload, start_ms, end_ms, task_id, upload_by), daemon=True).start()
        return self.status()

    def cancel(self) -> dict:
        self._cancel.set(); self._set(message="正在取消"); return self.status()

    def _run(self, payload: ExtractRequest, start_ms: int, end_ms: int,
             task_id: str, upload_by: str) -> None:
        excluded = {str(value) for value in payload.selection.excludedMessageIds}
        explicit = {str(value) for value in payload.selection.selectedMessageIds}
        cursor = ""; seen_cursors = set(); messages = []; scanned = 0
        try:
            while True:
                if self._cancel.is_set():
                    self._set(running=False, status="cancelled", message="任务已取消"); return
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
            if not messages: raise RuntimeError("所选范围内没有可提取的消息")
            if self._cancel.is_set():
                self._set(running=False, status="cancelled", message="任务已取消"); return
            def progress(status, message): self._set(status=status, message=message)
            result = self.processor.process(messages, payload.promptContent, upload_by, task_id, progress)
            self._set(running=False, status="done", message="经验提取并入库完成", **result)
        except Exception as exc:
            self._set(running=False, status="failed", error=str(exc), message="提取任务失败")
