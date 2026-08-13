from __future__ import annotations

import threading
import uuid
from datetime import datetime

import requests

from .models import ExtractRequest
from .store import GroupStore
from .welink import WelinkHistory


class ExtractionRuntime:
    def __init__(self, history: WelinkHistory, groups: GroupStore,
                 cloud_url: str, default_upload_by: str = ""):
        self.history = history
        self.groups = groups
        self.cloud_url = cloud_url.rstrip("/")
        self.default_upload_by = default_upload_by
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._task = self._idle()

    @staticmethod
    def _idle() -> dict:
        return {"running": False, "taskId": "", "importId": "", "status": "idle",
                "scanned": 0, "selected": 0, "uploaded": 0, "chunks": 0,
                "message": "", "error": ""}

    def status(self) -> dict:
        with self._lock:
            return dict(self._task)

    def _set(self, **changes) -> None:
        with self._lock:
            self._task.update(changes)

    def start(self, payload: ExtractRequest, start_ms: int, end_ms: int) -> dict:
        if payload.extractMode == "draft":
            raise ValueError("云端草稿审核尚未实现，请先选择直接入库")
        if not self.cloud_url.startswith("https://") and not self.cloud_url.startswith("http://localhost"):
            raise ValueError("COREINSIGHT_CLOUD_URL 必须使用 HTTPS")
        group = self.groups.get(payload.groupId)
        if not group:
            raise ValueError("请先绑定该群组")
        with self._lock:
            if self._task.get("running") or self._task.get("status") == "processing":
                raise RuntimeError("已有聊天记录提取任务正在执行")
            task_id = uuid.uuid4().hex
            import_id = uuid.uuid4().hex
            self._task = {"running": True, "taskId": task_id, "importId": import_id,
                          "status": "starting", "scanned": 0, "selected": 0,
                          "uploaded": 0, "chunks": 0, "message": "正在创建上传批次", "error": ""}
            self._cancel.clear()
        threading.Thread(target=self._run, args=(payload, group.name or group.groupId,
                         start_ms, end_ms, import_id), daemon=True).start()
        return self.status()

    def cancel(self) -> dict:
        self._cancel.set()
        self._set(message="正在取消")
        return self.status()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = requests.request(method, f"{self.cloud_url}{path}", timeout=120,
                                    verify=False, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not data.get("Success", False):
            raise RuntimeError(data.get("Message") or "云端拒绝请求")
        return data

    def _run(self, payload: ExtractRequest, group_name: str, start_ms: int,
             end_ms: int, import_id: str) -> None:
        selection = payload.selection
        excluded = {str(value) for value in selection.excludedMessageIds}
        explicit = {str(value) for value in selection.selectedMessageIds}
        cursor = ""
        buffer: list[dict] = []
        scanned = selected = uploaded = chunks = 0
        try:
            self._request("POST", "/api/welink/imports", json={
                "importId": import_id, "groupId": payload.groupId,
                "groupName": group_name, "startTime": start_ms, "endTime": end_ms,
                "uploadBy": payload.uploadBy.strip() or self.default_upload_by,
                "promptContent": payload.promptContent,
            })
            self._set(status="fetching", message="正在读取并筛选 WeLink 消息")
            seen_cursors = set()
            while True:
                if self._cancel.is_set():
                    self._set(running=False, status="cancelled", message="任务已取消")
                    return
                page = self.history.fetch_page(payload.groupId, start_ms, end_ms, cursor, 100)
                scanned += len(page["items"])
                for item in page["items"]:
                    message_id = str(item["id"])
                    include = message_id not in excluded if selection.mode == "all" else message_id in explicit
                    if include:
                        buffer.append(item)
                        selected += 1
                    if len(buffer) >= 200:
                        self._upload_chunk(import_id, chunks, buffer)
                        uploaded += len(buffer); chunks += 1; buffer = []
                self._set(scanned=scanned, selected=selected, uploaded=uploaded,
                          chunks=chunks, message=f"已扫描 {scanned} 条，选中 {selected} 条")
                next_cursor = page["nextCursor"]
                if selection.mode == "explicit" and explicit and selected >= len(explicit):
                    break
                if not page["hasMore"] or not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor); cursor = next_cursor
            if buffer:
                self._upload_chunk(import_id, chunks, buffer)
                uploaded += len(buffer); chunks += 1
            if not uploaded:
                raise RuntimeError("所选范围内没有可提取的消息")
            self._set(status="submitting", uploaded=uploaded, chunks=chunks,
                      message="消息上传完成，正在提交云端提取")
            result = self._request("POST", f"/api/welink/imports/{import_id}/complete",
                                   json={"chunkCount": chunks, "messageCount": uploaded})
            self._set(running=False, status="processing", uploaded=uploaded, chunks=chunks,
                      chatId=result.get("ChatId", ""), message="云端正在提取经验")
        except Exception as exc:
            self._set(running=False, status="failed", error=str(exc), message="提取任务失败")

    def _upload_chunk(self, import_id: str, index: int, messages: list[dict]) -> None:
        self._set(status="uploading", message=f"正在上传第 {index + 1} 个消息分块")
        messages = sorted(
            messages, key=lambda item: (int(item.get("timestamp") or 0), str(item.get("id") or ""))
        )
        self._request("POST", f"/api/welink/imports/{import_id}/chunks/{index}",
                      json={"messages": messages})

    def refresh_cloud_status(self) -> dict:
        task = self.status()
        if task.get("status") != "processing" or not task.get("importId"):
            return task
        try:
            result = self._request("GET", f"/api/welink/imports/{task['importId']}")
            cloud_status = (result.get("Import") or {}).get("status", "processing")
            message = {"done": "经验提取并入库完成", "failed": "云端经验提取失败"}.get(
                cloud_status, "云端正在提取经验")
            self._set(status=cloud_status, message=message,
                      error="云端经验提取失败" if cloud_status == "failed" else "")
        except Exception as exc:
            self._set(error=f"状态查询失败：{exc}")
        return self.status()
