from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone


_STARTUPINFO = None
if sys.platform == "win32":
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW


class WelinkHistory:
    def __init__(self, executable: str = "welink-cli"):
        self.executable = executable

    def _run(self, args: list[str], timeout: int = 60) -> dict:
        try:
            result = subprocess.run(
                [self.executable, *args], capture_output=True, text=True,
                encoding="utf-8", errors="ignore", timeout=timeout,
                startupinfo=_STARTUPINFO,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("未找到 welink-cli，请先安装并登录 WeLink CLI") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("WeLink 历史消息查询超时") from exc
        output = result.stdout.strip()
        if not output:
            detail = result.stderr.strip()[:300] if result.stderr else "无输出"
            raise RuntimeError(f"welink-cli 查询失败：{detail}")
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError("welink-cli 返回内容不是有效 JSON") from exc
        if str(data.get("resultCode", "0")) != "0":
            raise RuntimeError(data.get("resultContext") or f"resultCode={data.get('resultCode')}")
        return data

    def query_page(self, group_id: str, message_id: str = "", count: int = 100) -> dict:
        args = [
            "im", "query-history-message", "--group-id", group_id,
            "--query-count", str(max(1, min(100, int(count)))),
        ]
        if message_id:
            # WeLink CLI: direction=0 returns messages older than message-id;
            # direction=1 returns newer messages. The first page needs neither.
            args.extend(["--message-id", message_id, "--query-direction", "0"])
        body = (self._run(args).get("respData") or {})
        return {
            "items": body.get("chatInfo") or [],
            "minMsgId": str(body.get("minMsgId") or ""),
            # Despite its name, msgTotalCount is the number of rows in this
            # response, not the total size of the conversation history.
            "count": int(body.get("msgTotalCount") or len(body.get("chatInfo") or [])),
        }

    def fetch(self, group_id: str, start_ms: int = 0, end_ms: int = 0) -> list[dict]:
        cursor = ""
        seen_cursors: set[str] = set()
        by_id: dict[str, dict] = {}
        while True:
            page = self.fetch_page(group_id, start_ms, end_ms, cursor, 100)
            for item in page["items"]:
                by_id[item["id"]] = item
            next_cursor = page["nextCursor"]
            if not page["hasMore"] or not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return sorted(by_id.values(), key=lambda item: (item["timestamp"], item["id"]))

    def fetch_page(self, group_id: str, start_ms: int = 0, end_ms: int = 0,
                   cursor: str = "", limit: int = 100) -> dict:
        """Return at most one visible page and a cursor for older messages.

        Pages newer than ``end_ms`` are skipped internally. A short CLI page is not
        treated as the end: some WeLink versions return fewer rows than requested
        while still exposing an older ``minMsgId`` cursor.
        """
        limit = max(1, min(100, int(limit)))
        current_cursor = str(cursor or "")
        scanned_cursors: set[str] = set()
        for _ in range(50):
            page = self.query_page(group_id, current_cursor, count=limit)
            raw_items = page.get("items") or []
            if not raw_items:
                return {"items": [], "nextCursor": "", "hasMore": False,
                        "totalHint": 0}

            times = [int(raw.get("serverSendTime") or 0) for raw in raw_items
                     if int(raw.get("serverSendTime") or 0)]
            visible = {}
            for raw in raw_items:
                message_id = str(raw.get("msgId") or "")
                timestamp = int(raw.get("serverSendTime") or 0)
                # WeLink commonly repeats the cursor row at the page boundary.
                if not message_id or (current_cursor and message_id == current_cursor):
                    continue
                if start_ms and timestamp < start_ms:
                    continue
                if end_ms and timestamp > end_ms:
                    continue
                visible[message_id] = self.normalize(raw)

            crossed_start = bool(start_ms and times and min(times) < start_ms)
            next_cursor = str(page.get("minMsgId") or self._minimum_id(raw_items))
            stalled = not next_cursor or next_cursor == current_cursor or next_cursor in scanned_cursors
            has_more = not crossed_start and not stalled
            if visible or not has_more:
                items = sorted(
                    visible.values(), key=lambda item: (item["timestamp"], item["id"]),
                    reverse=True,
                )
                return {"items": items, "nextCursor": next_cursor if has_more else "",
                        "hasMore": has_more, "totalHint": 0}

            scanned_cursors.add(next_cursor)
            current_cursor = next_cursor

        raise RuntimeError("连续扫描 50 页仍未到达指定时间范围，请缩小查询范围")

    @staticmethod
    def _minimum_id(items: list[dict]) -> str:
        values = [str(item.get("msgId")) for item in items if item.get("msgId") is not None]
        if not values:
            return ""
        return min(values, key=lambda value: (0, int(value)) if value.isdigit() else (1, value))

    @staticmethod
    def normalize(raw: dict) -> dict:
        timestamp = int(raw.get("serverSendTime") or 0)
        content_type = str(raw.get("contentType") or "TEXT_MSG")
        content = str(raw.get("content") or "")
        display = {
            "PICTURE_MSG": "[图片]",
            "FILE_MSG": "[文件]",
            "CARD_MSG": "[卡片消息]",
        }.get(content_type, content)
        if content_type == "NOTICE_MSG":
            display = f"[系统通知] {content}"
        return {
            "id": str(raw.get("msgId") or ""),
            "sender": str(raw.get("sender") or ""),
            "time": datetime.fromtimestamp(timestamp / 1000, timezone.utc).astimezone().isoformat(timespec="seconds")
            if timestamp else "",
            "content": display,
            "checked": True,
            "contentType": content_type,
            "timestamp": timestamp,
        }
