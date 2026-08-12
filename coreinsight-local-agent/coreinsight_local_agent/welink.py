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
            args.extend(["--message-id", message_id, "--query-direction", "1"])
        body = (self._run(args).get("respData") or {})
        return {
            "items": body.get("chatInfo") or [],
            "minMsgId": str(body.get("minMsgId") or ""),
            "total": int(body.get("msgTotalCount") or 0),
        }

    def fetch(self, group_id: str, start_ms: int = 0, end_ms: int = 0) -> list[dict]:
        cursor = ""
        seen_cursors: set[str] = set()
        by_id: dict[str, dict] = {}
        while True:
            page = self.query_page(group_id, cursor)
            raw_items = page["items"]
            if not raw_items:
                break
            times = []
            for raw in raw_items:
                message_id = str(raw.get("msgId") or "")
                timestamp = int(raw.get("serverSendTime") or 0)
                if timestamp:
                    times.append(timestamp)
                if not message_id:
                    continue
                if start_ms and timestamp < start_ms:
                    continue
                if end_ms and timestamp > end_ms:
                    continue
                by_id[message_id] = self.normalize(raw)
            if start_ms and times and min(times) < start_ms:
                break
            next_cursor = page.get("minMsgId") or self._minimum_id(raw_items)
            if not next_cursor or next_cursor in seen_cursors or len(raw_items) < 100:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return sorted(by_id.values(), key=lambda item: (item["timestamp"], item["id"]))

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
