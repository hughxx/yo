from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import threading
import uuid

from .models import ExtractRequest
from .processor import ExtractionCancelled, LocalExperienceProcessor
from .store import GroupStore
from .welink import WelinkHistory

logger = logging.getLogger(__name__)


@dataclass
class _Job:
    payload: ExtractRequest
    start_ms: int
    end_ms: int
    task_id: str
    upload_by: str
    scheduled: bool
    on_complete: object
    cancel: threading.Event


class ExtractionRuntime:
    def __init__(self, history: WelinkHistory, groups: GroupStore,
                 processor: LocalExperienceProcessor, default_upload_by: str = '',
                 notifier=None):
        self.history = history
        self.groups = groups
        self.processor = processor
        self.default_upload_by = default_upload_by
        self.notifier = notifier
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._stop = False
        self._queue: deque[_Job] = deque()
        self._tasks: dict[str, dict] = {}
        self._group_tasks: dict[str, str] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._active_task_id = ''
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    @staticmethod
    def _idle() -> dict:
        return {'running': False, 'taskId': '', 'status': 'idle', 'scanned': 0,
                'selected': 0, 'message': '', 'error': '', 'docId': '', 'title': ''}

    def status(self, task_id: str = '', group_id: str = '') -> dict | None:
        with self._lock:
            if task_id:
                task = self._tasks.get(task_id)
                return dict(task) if task else None
            if group_id:
                current = self._group_tasks.get(group_id)
                if current:
                    return dict(self._tasks[current])
                for task in reversed(self._tasks.values()):
                    if task.get('groupId') == group_id:
                        return dict(task)
                return None
            if self._active_task_id:
                return dict(self._tasks[self._active_task_id])
            if self._tasks:
                return dict(next(reversed(self._tasks.values())))
            return self._idle()

    def tasks(self) -> list[dict]:
        with self._lock:
            return [dict(task) for task in reversed(self._tasks.values())]

    def _set(self, task_id: str, **changes) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].update(changes)

    def start(self, payload: ExtractRequest, start_ms: int, end_ms: int,
              scheduled: bool = False, on_complete=None) -> dict:
        if not self.groups.get(payload.groupId):
            raise ValueError('请先绑定该群组')
        upload_by = payload.uploadBy.strip() or self.default_upload_by
        self.processor.validate(upload_by, payload.skillId, payload.extractMode)
        with self._condition:
            if payload.groupId in self._group_tasks:
                raise RuntimeError('该群组已有提取任务正在执行或排队')
            task_id = uuid.uuid4().hex
            cancel = threading.Event()
            task = {'running': True, 'taskId': task_id, 'status': 'queued',
                    'groupId': payload.groupId, 'scheduled': scheduled,
                    'scanned': 0, 'selected': 0, 'message': '任务已排队',
                    'error': '', 'docId': '', 'title': ''}
            self._tasks[task_id] = task
            self._group_tasks[payload.groupId] = task_id
            self._cancels[task_id] = cancel
            self._queue.append(_Job(payload, start_ms, end_ms, task_id, upload_by,
                                    scheduled, on_complete, cancel))
            self.groups.set_status(payload.groupId, 'extracting')
            self._trim_finished_tasks()
            self._condition.notify()
        logger.info('extraction queued task_id=%s group_id=%s scheduled=%s',
                    task_id, payload.groupId, scheduled)
        return dict(task)

    def cancel(self, task_id: str = '', group_id: str = '') -> dict | None:
        with self._lock:
            if not task_id and group_id:
                task_id = self._group_tasks.get(group_id, '')
            if not task_id:
                task_id = self._active_task_id
            task = self._tasks.get(task_id) if task_id else None
            if not task:
                return None
            if not task.get('running'):
                return dict(task)
            self._cancels[task_id].set()
            if task.get('status') == 'queued':
                task.update(running=False, status='cancelled', message='任务已取消')
                if self._group_tasks.get(task['groupId']) == task_id:
                    self._group_tasks.pop(task['groupId'], None)
                self._cancels.pop(task_id, None)
                self._restore_group_status(task['groupId'])
            else:
                task['message'] = '正在取消（当前网络请求返回后停止）'
            return dict(task)

    def close(self) -> None:
        with self._condition:
            self._stop = True
            for cancel in self._cancels.values():
                cancel.set()
            self._condition.notify_all()
        # Give the active worker a short grace period to stop its Hermes run
        # and execute normal workspace cleanup before the process exits.
        if self._worker is not threading.current_thread():
            self._worker.join(timeout=5)

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._stop:
                    self._condition.wait()
                if self._stop:
                    return
                job = self._queue.popleft()
                task = self._tasks.get(job.task_id)
                if not task or not task.get('running'):
                    continue
                self._active_task_id = job.task_id
                task.update(status='fetching', message='正在本地读取并筛选 WeLink 消息')
            self._run(job)
            with self._lock:
                if self._active_task_id == job.task_id:
                    self._active_task_id = ''

    def _run(self, job: _Job) -> None:
        payload = job.payload
        excluded = {str(value) for value in payload.selection.excludedMessageIds}
        explicit = {str(value) for value in payload.selection.selectedMessageIds}
        cursor = ''
        seen_cursors = set()
        messages = []
        scanned = 0
        try:
            while True:
                if job.cancel.is_set():
                    self._cancelled(job)
                    return
                page = self.history.fetch_page(
                    payload.groupId, job.start_ms, job.end_ms, cursor, 100)
                scanned += len(page['items'])
                for item in page['items']:
                    if job.scheduled and int(item.get('timestamp') or 0) <= job.start_ms:
                        continue
                    message_id = str(item['id'])
                    include = (message_id not in excluded
                               if payload.selection.mode == 'all'
                               else message_id in explicit)
                    if include:
                        messages.append(item)
                self._set(job.task_id, scanned=scanned, selected=len(messages),
                          message=f'本地已扫描 {scanned} 条，选中 {len(messages)} 条')
                next_cursor = page['nextCursor']
                if payload.selection.mode == 'explicit' and explicit and len(messages) >= len(explicit):
                    break
                if not page['hasMore'] or not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            logger.info('messages fetched task_id=%s scanned=%d selected=%d',
                        job.task_id, scanned, len(messages))
            if not messages and job.scheduled:
                self._notify(job, True, {})
                self._finish(job, status='done', message='本次没有新增消息')
                return
            if not messages:
                raise RuntimeError('所选范围内没有可提取的消息')
            if job.cancel.is_set():
                self._cancelled(job)
                return

            def progress(status, message):
                self._set(job.task_id, status=status, message=message)

            result = self.processor.process(
                messages, payload.skillId, job.upload_by, job.task_id,
                progress, job.cancel, group_id=payload.groupId,
                scheduled=job.scheduled, extract_mode=payload.extractMode)
            if self.notifier:
                experiences = result.get('experiences') or []
                try:
                    self.notifier.notify(
                        job.upload_by, payload.extractMode, experiences,
                        source_type="welink")
                except TypeError as exc:
                    if "source_type" not in str(exc):
                        raise
                    self.notifier.notify(
                        job.upload_by, payload.extractMode, experiences)
            message = ('草稿提取完成，已进入平台待审核列表'
                       if payload.extractMode == 'draft'
                       else '经验提取并入库完成')
            self._notify(job, True, result)
            self._finish(job, status='done', message=message, **result)
            logger.info('extraction completed task_id=%s experiences=%s',
                        job.task_id, result.get('experienceCount', 0))
        except ExtractionCancelled:
            logger.info('extraction cancelled task_id=%s', job.task_id)
            self._cancelled(job)
        except Exception as exc:
            logger.exception('extraction failed task_id=%s group_id=%s',
                             job.task_id, payload.groupId)
            self._notify(job, False, {'error': str(exc)})
            self._finish(job, status='failed', error=str(exc),
                         message='提取任务失败')

    def _finish(self, job: _Job, **changes) -> None:
        with self._lock:
            task = self._tasks.get(job.task_id)
            if task:
                task.update(**changes)
        self._restore_group_status(job.payload.groupId)
        with self._lock:
            if self._group_tasks.get(job.payload.groupId) == job.task_id:
                self._group_tasks.pop(job.payload.groupId, None)
            self._cancels.pop(job.task_id, None)
            if task:
                task['running'] = False

    def _restore_group_status(self, group_id: str) -> None:
        group = self.groups.get(group_id)
        if group:
            status = 'scheduled' if group.scheduleEnabled else 'idle'
            self.groups.set_status(group_id, status)

    def _cancelled(self, job: _Job) -> None:
        self._finish(job, status='cancelled', message='任务已取消')

    def _notify(self, job: _Job, success: bool, result: dict) -> None:
        if not job.on_complete:
            return
        try:
            job.on_complete(success, job.end_ms, result)
        except Exception:
            logger.exception('extraction completion callback failed task_id=%s',
                             job.task_id)

    def _trim_finished_tasks(self) -> None:
        if len(self._tasks) <= 100:
            return
        removable = [key for key, value in self._tasks.items()
                     if not value.get('running')]
        for task_id in removable[:len(self._tasks) - 100]:
            self._tasks.pop(task_id, None)
