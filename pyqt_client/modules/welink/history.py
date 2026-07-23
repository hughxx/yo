"""WeLink 历史会话分页查询与聊天记录标准化。"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from html import escape

import requests


_STARTUPINFO = None
if sys.platform == "win32":
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW


def _run_cli(args: list[str], timeout: int = 60) -> dict:
    try:
        result = subprocess.run(
            ["welink-cli", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
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
        raise RuntimeError(f"welink-cli 返回内容不是有效 JSON：{exc}") from exc
    if str(data.get("resultCode", "0")) != "0":
        raise RuntimeError(data.get("resultContext") or f"resultCode={data.get('resultCode')}")
    return data


def source_key(source: dict) -> str:
    kind = "user" if source.get("type") == "user" else "group"
    return f"{kind}:{str(source.get('source_id', '')).strip()}"


def query_page(source: dict, message_id: str = "", older: bool = False,
               count: int = 100) -> dict:
    """查询一页。首屏不传 message-id；后续用最小 ID 向旧消息翻页。"""
    source_id = str(source.get("source_id", "")).strip()
    if not source_id:
        raise ValueError("聊天来源 ID 不能为空")
    selector = "--user-account" if source.get("type") == "user" else "--group-id"
    args = ["im", "query-history-message", selector, source_id,
            "--query-count", str(max(1, min(100, int(count))))]
    if message_id:
        args.extend(["--message-id", str(message_id),
                     "--query-direction", "1" if older else "0"])
    data = _run_cli(args)
    body = data.get("respData") or {}
    return {
        "items": body.get("chatInfo") or [],
        "minMsgId": str(body.get("minMsgId") or ""),
        "maxMsgId": str(body.get("maxMsgId") or ""),
        "total": int(body.get("msgTotalCount") or 0),
    }


def fetch_history(source: dict, start_ms: int = 0, end_ms: int = 0,
                  progress=None) -> list[dict]:
    """从最新消息向前分页，直到到达时间下界；start_ms=0 表示完整历史。"""
    start_ms = max(0, int(start_ms or 0))
    end_ms = max(0, int(end_ms or 0))
    cursor = ""
    seen_cursors: set[str] = set()
    by_id: dict[str, dict] = {}
    page_number = 0
    while True:
        page = query_page(source, cursor, older=bool(cursor), count=100)
        page_number += 1
        raw_items = page["items"]
        if not raw_items:
            break
        times = []
        for raw in raw_items:
            msg_id = str(raw.get("msgId") or "")
            timestamp = int(raw.get("serverSendTime") or 0)
            if timestamp:
                times.append(timestamp)
            if not msg_id or (start_ms and timestamp < start_ms) or (end_ms and timestamp > end_ms):
                continue
            by_id[msg_id] = normalize_message(raw)
        if progress:
            progress(page_number, len(by_id), page.get("total", 0))
        if start_ms and times and min(times) < start_ms:
            break
        next_cursor = page.get("minMsgId") or min(
            (str(x.get("msgId")) for x in raw_items if x.get("msgId") is not None),
            default="",
            key=lambda value: int(value),
        )
        if not next_cursor or next_cursor in seen_cursors or len(raw_items) < 100:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return sorted(by_id.values(), key=lambda item: (item["timestamp"], int(item["id"])))


def normalize_message(raw: dict) -> dict:
    timestamp = int(raw.get("serverSendTime") or 0)
    content_type = str(raw.get("contentType") or "TEXT_MSG")
    content = str(raw.get("content") or "")
    display = content
    if content_type == "PICTURE_MSG":
        display = "[图片]"
    elif content_type == "FILE_MSG":
        display = "[文件]"
    elif content_type == "CARD_MSG":
        display = "[卡片消息]"
    elif content_type == "NOTICE_MSG":
        display = f"[系统通知] {content}"
    return {
        "id": str(raw.get("msgId") or ""),
        "sender": str(raw.get("sender") or ""),
        "receiver": str(raw.get("receiver") or ""),
        "content": content,
        "displayContent": display,
        "contentType": content_type,
        "timestamp": timestamp,
        "time": datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "",
        "raw": raw,
    }


def _parse_um_content(content: str):
    prefix, suffix = "/:um_begin{", "}/:um_end"
    if not (content.startswith(prefix) and content.endswith(suffix)):
        return None, None, None
    parts = content[len(prefix):-len(suffix)].split("|")
    if len(parts) < 6:
        return None, None, None
    fields = parts[5].split(";")
    return parts[0], parts[3], fields[2] if len(fields) > 2 else ""


def enrich_images_inplace(messages: list[dict], backend_base: str, log_fn) -> None:
    """通过后端代理转换 WeLink 图片/文件链接，供挖掘服务读取。"""
    for message in messages:
        if message.get("contentType") not in ("PICTURE_MSG", "FILE_MSG"):
            continue
        download_url, filename, extraction_code = _parse_um_content(message.get("content", ""))
        if not download_url or not filename:
            continue
        message["_img_name"] = filename
        try:
            response = requests.post(
                f"{backend_base}/api/image/proxy",
                json={"download_url": download_url, "extraction_code": extraction_code,
                      "file_name": filename},
                timeout=60,
                verify=False,
            )
            data = response.json()
            if data.get("success") and data.get("url"):
                message["_img_url"] = data["url"]
            else:
                log_fn(f"图片下载失败：{filename}（{data.get('message', '')}）")
        except Exception as exc:
            log_fn(f"图片请求失败：{filename}（{exc}）")


def messages_to_html(messages: list[dict]) -> str:
    rows = []
    for message in messages:
        timestamp = int(message.get("serverSendTime") or 0)
        time_text = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S") if timestamp else ""
        sender = escape(str(message.get("sender") or ""))
        content_type = message.get("contentType", "")
        raw = str(message.get("content") or "")
        if content_type in ("PICTURE_MSG", "FILE_MSG"):
            url = message.get("_img_url")
            filename = escape(str(message.get("_img_name") or ""))
            if content_type == "PICTURE_MSG" and url:
                body = f'<img src="{escape(url)}" style="max-width:480px;display:block"><small>{filename}</small>'
            elif content_type == "FILE_MSG" and url:
                body = f'<a href="{escape(url)}">[文件] {filename}</a>'
            else:
                body = f'<em>[{"图片" if content_type == "PICTURE_MSG" else "文件"}] {filename}</em>'
        elif content_type == "CARD_MSG":
            body = "<em>[卡片消息]</em>"
        elif content_type == "NOTICE_MSG":
            body = f"<em>[系统通知] {escape(raw)}</em>"
        else:
            body = raw if raw.strip().startswith("<") else escape(raw).replace("\n", "<br>")
        rows.append(
            '<div style="margin:6px 0;padding:6px 10px;background:#f5f5f5;border-radius:4px">'
            f'<span style="font-weight:bold;color:#1a73e8">{sender}</span>'
            f'<span style="font-size:11px;color:#aaa;margin-left:8px">{time_text}</span>'
            f'<div style="margin-top:4px">{body}</div></div>'
        )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        'body{font-family:Arial,sans-serif;font-size:13px;color:#222;max-width:860px;margin:20px auto;padding:0 16px}'
        '</style></head><body>' + "".join(rows) + "</body></html>"
    )
