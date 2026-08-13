from __future__ import annotations

import calendar
import threading
from datetime import datetime, timedelta

from .extraction import ExtractionRuntime
from .models import ExtractRequest, ScheduleSetRequest
from .store import GroupStore


def _parse_time(value: str) -> tuple[int, int, int]:
    try:
        parts = [int(item) for item in value.split(":")]
        if len(parts) == 2:
            parts.append(0)
        hour, minute, second = parts
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            raise ValueError
        return hour, minute, second
    except (TypeError, ValueError):
        raise ValueError("scheduleTime 必须是 HH:mm 或 HH:mm:ss")


def _cron_values(field: str, minimum: int, maximum: int) -> set[int]:
    if field == "?":
        field = "*"
    values = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("Cron 字段不能为空")
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            step = int(raw_step)
            if step < 1:
                raise ValueError("Cron 步长必须大于 0")
        if part == "*":
            start, end = minimum, maximum
        elif "-" in part:
            start, end = (int(value) for value in part.split("-", 1))
        else:
            start = end = int(part)
        if start < minimum or end > maximum or start > end:
            raise ValueError("Cron 字段超出范围")
        values.update(range(start, end + 1, step))
    return values


def next_cron(cron: str, after: datetime) -> datetime:
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError("Cron 必须包含 5 个字段：分 时 日 月 星期")
    minutes = _cron_values(fields[0], 0, 59)
    hours = _cron_values(fields[1], 0, 23)
    days = _cron_values(fields[2], 1, 31)
    months = _cron_values(fields[3], 1, 12)
    weekdays = {0 if value == 7 else value for value in _cron_values(fields[4], 0, 7)}
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = candidate + timedelta(days=366 * 2)
    while candidate <= limit:
        cron_weekday = (candidate.weekday() + 1) % 7
        day_matches = candidate.day in days
        weekday_matches = cron_weekday in weekdays
        if fields[2] not in ("*", "?") and fields[4] not in ("*", "?"):
            calendar_matches = day_matches or weekday_matches
        else:
            calendar_matches = day_matches and weekday_matches
        if (candidate.minute in minutes and candidate.hour in hours and
                candidate.month in months and calendar_matches):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError("未来两年内找不到符合 Cron 的执行时间")


def next_run(group, after: datetime) -> datetime:
    if group.scheduleFreq == "custom":
        return next_cron(group.scheduleCron, after)
    hour, minute, second = _parse_time(group.scheduleTime)
    if group.scheduleFreq == "daily":
        candidate = after.replace(hour=hour, minute=minute, second=second, microsecond=0)
        return candidate if candidate > after else candidate + timedelta(days=1)
    if group.scheduleFreq == "weekly":
        days = (group.scheduleWeekday - after.weekday()) % 7
        candidate = (after + timedelta(days=days)).replace(
            hour=hour, minute=minute, second=second, microsecond=0)
        return candidate if candidate > after else candidate + timedelta(days=7)
    for month_offset in range(14):
        year = after.year + (after.month - 1 + month_offset) // 12
        month = (after.month - 1 + month_offset) % 12 + 1
        if group.scheduleDay > calendar.monthrange(year, month)[1]:
            continue
        candidate = after.replace(year=year, month=month, day=group.scheduleDay,
                                  hour=hour, minute=minute, second=second, microsecond=0)
        if candidate > after:
            return candidate
    raise ValueError("无法计算下次每月执行时间")


class ScheduleRuntime:
    def __init__(self, groups: GroupStore, extraction: ExtractionRuntime):
        self.groups = groups
        self.extraction = extraction
        self._stop = threading.Event()
        self.refresh_next_runs()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()

    def set(self, payload: ScheduleSetRequest, now: datetime | None = None):
        now = now or datetime.now().astimezone()
        group = self.groups.get(payload.groupId)
        if not group:
            raise ValueError("请先绑定该群组")
        self.extraction.processor.validate(payload.uploadBy.strip(), payload.skillId)
        _parse_time(payload.scheduleTime)
        group.skillId = payload.skillId
        group.uploadBy = payload.uploadBy.strip()
        group.extractMode = payload.extractMode
        group.scheduleFreq = payload.scheduleFreq
        group.scheduleTime = payload.scheduleTime
        group.scheduleCron = payload.scheduleCron.strip()
        group.scheduleWeekday = now.weekday()
        group.scheduleDay = now.day
        group.scheduleEnabled = True
        if not group.scheduleLastRun:
            group.scheduleLastRun = now.isoformat(timespec="seconds")
        group.scheduleNextRun = next_run(group, now).isoformat(timespec="seconds")
        group.status = "scheduled"
        return self.groups.update(group)

    def cancel(self, group_id: str):
        group = self.groups.get(group_id)
        if not group:
            raise ValueError("群组不存在")
        task = self.extraction.status()
        if task.get("running") and task.get("groupId") == group_id and task.get("scheduled"):
            self.extraction.cancel()
        group.scheduleEnabled = False
        group.scheduleNextRun = ""
        group.status = "extracting" if task.get("running") and task.get("groupId") == group_id else "idle"
        return self.groups.update(group)

    def refresh_next_runs(self, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        for group in self.groups.list():
            if not group.scheduleEnabled:
                continue
            try:
                if not group.scheduleNextRun:
                    group.scheduleNextRun = next_run(group, now).isoformat(timespec="seconds")
                if group.status != "extracting":
                    group.status = "scheduled"
                self.groups.update(group)
            except ValueError:
                group.scheduleEnabled = False
                group.scheduleNextRun = ""
                group.status = "idle"
                self.groups.update(group)

    def tick(self, now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        if self.extraction.status().get("running"):
            return False
        for group in self.groups.list():
            if not group.scheduleEnabled or not group.scheduleNextRun:
                continue
            due = datetime.fromisoformat(group.scheduleNextRun)
            if due > now:
                continue
            start = datetime.fromisoformat(group.scheduleLastRun) if group.scheduleLastRun else due
            payload = ExtractRequest(
                groupId=group.groupId, uploadBy=group.uploadBy,
                skillId=group.skillId, extractMode="direct",
                selection={"mode": "all"})
            try:
                self.extraction.start(
                    payload, int(start.timestamp() * 1000), int(now.timestamp() * 1000),
                    scheduled=True,
                    on_complete=lambda ok, end_ms, result, gid=group.groupId: self._completed(gid, ok, end_ms),
                )
                return True
            except (RuntimeError, ValueError):
                return False
        return False

    def _completed(self, group_id: str, success: bool, end_ms: int) -> None:
        group = self.groups.get(group_id)
        if not group or not group.scheduleEnabled:
            return
        completed = datetime.fromtimestamp(end_ms / 1000).astimezone()
        if success:
            group.scheduleLastRun = completed.isoformat(timespec="seconds")
        group.scheduleNextRun = next_run(group, completed).isoformat(timespec="seconds")
        group.status = "scheduled"
        self.groups.update(group)

    def _loop(self) -> None:
        while not self._stop.wait(15):
            try:
                self.tick()
            except Exception:
                continue
