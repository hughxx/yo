from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

from .config import Settings
from .time_format import format_datetime


logger = logging.getLogger(__name__)
INBOX = 6
MAIL_ITEM_CLASS = 43
TABLE_BATCH_SIZE = 200
TABLE_COLUMNS = (
    "EntryID",
    "Subject",
    "SenderName",
    "SenderEmailAddress",
    "ReceivedTime",
    "ConversationTopic",
    "http://schemas.microsoft.com/mapi/proptag/0x0E1B000B",
    "MessageClass",
)
PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001E"
BODY_DASL_FIELD = '"urn:schemas:httpmail:textdescription"'
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


def _imports():
    try:
        import pythoncom
        import win32com.client
        import win32timezone  # noqa: F401
        return pythoncom, win32com.client
    except ImportError as exc:
        raise RuntimeError("未安装 Outlook 访问组件，请重新安装最新版 LocalToolkit") from exc


@contextmanager
def outlook_session():
    pythoncom, win32_client = _imports()
    pythoncom.CoInitialize()
    namespace = None
    try:
        namespace = win32_client.Dispatch(
            "Outlook.Application").GetNamespace("MAPI")
        yield namespace
    finally:
        namespace = None
        try:
            pythoncom.CoFreeUnusedLibraries()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def _get_folder(namespace, path: str):
    parts = path.split("\\")
    for store in namespace.Stores:
        try:
            root = store.GetRootFolder()
            if root.Name != parts[0] and store.DisplayName != parts[0]:
                continue
            folder = root
            for name in parts[1:]:
                folder = folder.Folders[name]
            return folder
        except Exception:
            continue
    raise FileNotFoundError(f"找不到 Outlook 文件夹：{path}")


def _folders(namespace, paths: list[str]):
    found = []
    for path in paths:
        try:
            found.append(_get_folder(namespace, path))
        except Exception:
            logger.warning("outlook folder unavailable path=%s", path)
    return found or [namespace.GetDefaultFolder(INBOX)]


def _collect_folders(folder, result: list[dict], prefix: str = ""):
    try:
        name = str(folder.Name)
        path = f"{prefix}\\{name}" if prefix else name
        result.append({"path": path, "name": name, "depth": path.count("\\"),
                       "_entryId": str(getattr(folder, "EntryID", "") or "")})
        children = list(folder.Folders)
    except Exception:
        return
    for child in children:
        _collect_folders(child, result, path)


def _sender_email(item, resolve_exchange: bool = True) -> str:
    value = str(getattr(item, "SenderEmailAddress", "") or "")
    if (not resolve_exchange
            or str(getattr(item, "SenderEmailType", "") or "").upper() != "EX"):
        return value
    try:
        exchange_user = item.Sender.GetExchangeUser()
        return str(exchange_user.PrimarySmtpAddress or value)
    except Exception:
        return value


def _received(item):
    value = getattr(item, "ReceivedTime", None)
    if not value:
        return None
    try:
        return value.astimezone()
    except Exception:
        return value


def _summary(item, folder_path: str, resolve_exchange: bool = True) -> dict:
    received = _received(item)
    return {
        "id": str(item.EntryID),
        "subject": str(getattr(item, "Subject", "") or ""),
        "senderName": str(getattr(item, "SenderName", "") or ""),
        "senderEmail": _sender_email(item, resolve_exchange),
        "receivedTime": format_datetime(received) if received else "",
        "timestamp": int(received.timestamp() * 1000) if received else 0,
        "conversationTopic": str(getattr(item, "ConversationTopic", "") or ""),
        "folder": folder_path,
        "hasAttachments": bool(getattr(item, "Attachments", None)
                               and item.Attachments.Count),
    }


def _table_array_rows(values) -> list[list]:
    """Normalize pywin32's SAFEARRAY into rows.

    Outlook documents GetArray as columns-by-rows, while pywin32 versions can
    expose the two-dimensional SAFEARRAY in either orientation.
    """
    matrix = [list(value) for value in (values or [])]
    if not matrix:
        return []
    column_count = len(TABLE_COLUMNS)
    if len(matrix) != column_count:
        return matrix
    row_dates = sum(
        1 for row in matrix
        if len(row) > 4 and hasattr(row[4], "timestamp"))
    column_dates = sum(
        1 for value in matrix[4]
        if hasattr(value, "timestamp"))
    if column_dates > row_dates:
        return [list(row) for row in zip(*matrix)]
    return matrix


def _table_summary(values: list, folder_path: str) -> dict | None:
    values = list(values) + [None] * (len(TABLE_COLUMNS) - len(values))
    message_class = str(values[7] or "")
    if message_class and not message_class.startswith("IPM.Note"):
        return None
    received = values[4]
    try:
        received = received.astimezone() if received else None
    except Exception:
        pass
    timestamp = int(received.timestamp() * 1000) if received else 0
    return {
        "id": str(values[0] or ""),
        "subject": str(values[1] or ""),
        "senderName": str(values[2] or ""),
        "senderEmail": str(values[3] or ""),
        "receivedTime": format_datetime(received) if received else "",
        "timestamp": timestamp,
        "conversationTopic": str(values[5] or ""),
        "folder": folder_path,
        "hasAttachments": bool(values[6]),
    }


def _fallback_html_to_markdown(content: str) -> str:
    content = re.sub(r"<br\s*/?>", "\n", content, flags=re.I)
    content = re.sub(r"</(?:p|div|li|tr|h[1-6])>", "\n", content, flags=re.I)
    content = re.sub(r"<[^>]+>", "", content)
    return html.unescape(content).strip()


def html_to_markdown(content: str) -> str:
    if not content:
        return ""
    try:
        import html2text
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = False
        converter.body_width = 0
        converter.ignore_emphasis = True
        converter.single_line_break = True
        converter.wrap_links = False
        converter.ul_item_mark = "-"
        markdown = converter.handle(content)
    except ImportError:
        markdown = _fallback_html_to_markdown(content)
    markdown = re.sub(r"!\[\]\(\)", "", markdown)
    markdown = markdown.replace("&nbsp;", " ")
    for codepoint in (0xA0, 0x2002, 0x2003, 0x2009, 0x202F):
        markdown = markdown.replace(chr(codepoint), " ")
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


class OutlookClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.Lock()
        self.preview_cache_dir = settings.data_dir / "email-preview-cache"

    def get_message_with_attachments(self, item_id: str) -> dict:
        """Return attachment-enriched HTML, reusing the local preview cache."""
        cache_path = self.preview_cache_dir / (
            hashlib.sha256(item_id.encode("utf-8")).hexdigest() + ".json")
        native = self.get_message(item_id, process_attachments=False)
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("sourceHtml") == native.get("htmlBody"):
                return cached["message"]
        except (OSError, ValueError, TypeError, KeyError):
            pass
        enriched = self.get_message(item_id, process_attachments=True)
        try:
            self.preview_cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({
                "sourceHtml": native.get("htmlBody", ""), "message": enriched,
            }, ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache_path)
        except (OSError, TypeError, ValueError):
            logger.warning("email preview cache write failed item_id=%s", item_id,
                           exc_info=True)
        return enriched

    def probe(self) -> dict:
        """Compatibility status; never start Outlook or open a MAPI session."""
        return {"installed": True, "ready": True, "account": "", "inbox": "",
                "message": "LocalToolkit 已就绪", "checking": False,
                "busy": self.lock.locked(), "checkedAt": ""}

    def list_folders(self) -> list[dict]:
        with self.lock, outlook_session() as namespace:
            result = []
            store = root = default_folder = None
            try:
                try:
                    default_folder = namespace.GetDefaultFolder(INBOX)
                    default_entry_id = str(
                        getattr(default_folder, "EntryID", "") or "")
                except Exception:
                    default_entry_id = ""
                for store in namespace.Stores:
                    try:
                        root = store.GetRootFolder()
                        _collect_folders(root, result)
                    except Exception:
                        continue
                for item in result:
                    item["isDefault"] = bool(
                        default_entry_id and item.get("_entryId") == default_entry_id)
                    item.pop("_entryId", None)
            finally:
                default_folder = None
                root = None
                store = None
            return result

    def list_messages(self, paths: list[str], start_ms: int = 0,
                      end_ms: int = 0, maximum: int = 10000,
                      progress=None, cancelled=None) -> list[dict]:
        """Read lightweight summaries through Outlook's bulk Table API."""
        try:
            return self._list_messages_table(
                paths, start_ms, end_ms, maximum, progress, cancelled)
        except Exception:
            logger.warning(
                "Outlook Table listing unavailable; falling back to Items",
                exc_info=True)
            return self._list_messages_items(
                paths, start_ms, end_ms, maximum, progress, cancelled)

    def _list_messages_table(self, paths: list[str], start_ms: int,
                             end_ms: int, maximum: int, progress=None,
                             cancelled=None) -> list[dict]:
        with self.lock, outlook_session() as namespace:
            result = []
            folders = _folders(namespace, paths)
            folder = table = columns = None
            total_count = 0
            inspected_count = 0
            try:
                for folder in folders:
                    if cancelled and cancelled():
                        break
                    folder_path = str(
                        getattr(folder, "FolderPath", "") or "").lstrip("\\")
                    table = folder.GetTable()
                    columns = table.Columns
                    columns.RemoveAll()
                    for column in TABLE_COLUMNS:
                        columns.Add(column)
                    table.Sort("ReceivedTime", True)
                    try:
                        total_count += int(table.GetRowCount())
                    except Exception:
                        pass
                    folder_count = 0
                    reached_start = False
                    while not table.EndOfTable and not reached_start:
                        if cancelled and cancelled():
                            break
                        batch = _table_array_rows(table.GetArray(TABLE_BATCH_SIZE))
                        if not batch:
                            break
                        inspected_count += len(batch)
                        for values in batch:
                            row = _table_summary(values, folder_path)
                            if row is None or not row["id"]:
                                continue
                            timestamp = row["timestamp"]
                            if end_ms and timestamp > end_ms:
                                continue
                            if start_ms and timestamp < start_ms:
                                reached_start = True
                                break
                            result.append(row)
                            folder_count += 1
                            if maximum > 0 and folder_count >= maximum:
                                reached_start = True
                                break
                        if progress:
                            progress(inspected_count,
                                     max(total_count, inspected_count))
            finally:
                columns = None
                table = None
                folder = None
                folders.clear()
            result.sort(
                key=lambda value: (value["timestamp"], value["id"]),
                reverse=True)
            return result if maximum <= 0 else result[:maximum]

    def _list_messages_items(self, paths: list[str], start_ms: int = 0,
                             end_ms: int = 0, maximum: int = 10000,
                             progress=None, cancelled=None) -> list[dict]:
        with self.lock, outlook_session() as namespace:
            result = []
            folders = _folders(namespace, paths)
            folder = items = item = None
            total_count = 0
            try:
                for folder in folders:
                    if cancelled and cancelled():
                        break
                    folder_path = str(getattr(folder, "FolderPath", "") or "").lstrip("\\")
                    try:
                        items = folder.Items
                        try:
                            total_count += int(items.Count)
                            if progress:
                                progress(len(result), total_count)
                        except Exception:
                            pass
                        items.Sort("[ReceivedTime]", True)
                        item = items.GetFirst()
                        folder_count = 0
                        # Read at most ``maximum`` rows from every sorted folder.  Taking
                        # the first K rows from each folder is sufficient to calculate
                        # the global first K rows after merging, and avoids one large
                        # folder starving all folders that follow it.
                        while item is not None and (maximum <= 0
                                                    or folder_count < maximum):
                            if cancelled and cancelled():
                                break
                            try:
                                if int(getattr(item, "Class", 0)) == MAIL_ITEM_CLASS:
                                    # Listing only needs lightweight metadata;
                                    # resolving Exchange users can perform an
                                    # extra COM lookup for every message.
                                    row = _summary(item, folder_path,
                                                   resolve_exchange=False)
                                    timestamp = row["timestamp"]
                                    if end_ms and timestamp > end_ms:
                                        item = items.GetNext()
                                        continue
                                    if start_ms and timestamp < start_ms:
                                        break
                                    result.append(row)
                                    folder_count += 1
                                    if progress:
                                        progress(len(result), total_count)
                            except Exception:
                                logger.debug("skip unreadable Outlook item", exc_info=True)
                            item = items.GetNext()
                    except Exception:
                        logger.warning("failed reading Outlook folder=%s", folder_path,
                                       exc_info=True)
            finally:
                item = None
                items = None
                folder = None
                folders.clear()
            result.sort(key=lambda value: (value["timestamp"], value["id"]), reverse=True)
            return result if maximum <= 0 else result[:maximum]

    def get_message(self, item_id: str, process_attachments: bool = True) -> dict:
        item = None
        with self.lock, outlook_session() as namespace:
            try:
                item = namespace.GetItemFromID(item_id)
                summary = _summary(item, "")
                html_body = str(getattr(item, "HTMLBody", "") or "")
                plain_body = str(getattr(item, "Body", "") or "")
                attachments = self._read_attachments(item, html_body) \
                    if process_attachments else []
            finally:
                item = None
        # Upload and OCR are network operations.  They must not keep MAPI, the COM
        # apartment, or the Outlook serialization lock alive for up to 300 seconds.
        html_body, attachment_markdown, attachment_rows = self._process_attachments(
            attachments, html_body)
        html_body = re.sub(r"src=[\"']cid:[^\"']*[\"']", 'src=""', html_body,
                           flags=re.I)
        body_markdown = html_to_markdown(html_body) if html_body else plain_body.strip()
        markdown = self._email_markdown(summary, body_markdown, attachment_markdown)
        return {**summary, "htmlBody": html_body, "body": plain_body,
                "markdown": markdown, "attachments": attachment_rows}

    def body_text(self, item_id: str) -> str:
        item = None
        with self.lock, outlook_session() as namespace:
            try:
                item = namespace.GetItemFromID(item_id)
                return str(getattr(item, "Body", "") or "")
            finally:
                item = None

    def body_texts(self, item_ids: list[str]) -> dict[str, str]:
        result = {}
        with self.lock, outlook_session() as namespace:
            item = None
            for item_id in item_ids:
                try:
                    item = namespace.GetItemFromID(item_id)
                    result[item_id] = str(getattr(item, "Body", "") or "")
                except Exception:
                    result[item_id] = ""
                finally:
                    item = None
        return result

    def search_body_matches(self, paths: list[str],
                            keyword_sets: list[list[str]]) -> list[set[str]]:
        """Ask Outlook/MAPI to match body keywords without copying every body."""
        results = [set() for _ in keyword_sets]
        with self.lock, outlook_session() as namespace:
            folders = _folders(namespace, paths)
            folder = restricted = item = None
            try:
                for index, keywords in enumerate(keyword_sets):
                    conditions = []
                    for keyword in keywords:
                        escaped = keyword.replace("'", "''")
                        conditions.append(f"{BODY_DASL_FIELD} LIKE '%{escaped}%'")
                    if not conditions:
                        continue
                    query = "@SQL=" + (conditions[0] if len(conditions) == 1
                                        else "(" + " OR ".join(conditions) + ")")
                    for folder in folders:
                        try:
                            restricted = folder.Items.Restrict(query)
                            item = restricted.GetFirst()
                            while item is not None:
                                try:
                                    results[index].add(str(item.EntryID))
                                except Exception:
                                    pass
                                item = restricted.GetNext()
                        except Exception:
                            logger.warning("Outlook body search failed", exc_info=True)
                            raise
            finally:
                item = None
                restricted = None
                folder = None
                folders.clear()
        return results

    @staticmethod
    def _read_attachments(item, html_body: str) -> list[dict]:
        """Copy attachment bytes while MAPI is alive; perform no network I/O."""
        copied = []
        referenced = set(re.findall(r"cid:([^\"'> ]+)", html_body, flags=re.I))
        attachment = None
        try:
            for attachment in item.Attachments:
                try:
                    filename = Path(str(
                        attachment.FileName or "attachment.bin")).name
                    suffix = Path(filename).suffix.lower()
                    cid = ""
                    try:
                        cid = str(attachment.PropertyAccessor.GetProperty(
                            PR_ATTACH_CONTENT_ID) or "").strip("<>")
                    except Exception:
                        pass
                    temporary = tempfile.NamedTemporaryFile(
                        delete=False, suffix=suffix or ".bin")
                    temporary.close()
                    try:
                        attachment.SaveAsFile(temporary.name)
                        copied.append({
                            "filename": filename, "suffix": suffix, "cid": cid,
                            "content": Path(temporary.name).read_bytes(),
                            "inline": bool(cid and cid in referenced),
                        })
                    finally:
                        try:
                            os.unlink(temporary.name)
                        except OSError:
                            pass
                except Exception as exc:
                    logger.warning("email attachment copy failed", exc_info=True)
                    copied.append({
                        "filename": str(getattr(attachment, "FileName", "attachment.bin")),
                        "suffix": "", "cid": "", "content": b"", "inline": False,
                        "readError": str(exc),
                    })
        finally:
            attachment = None
        return copied

    def _process_attachments(self, attachments: list[dict], html_body: str):
        markdown = []
        rows = []
        for attachment in attachments:
            filename = attachment["filename"]
            suffix = attachment["suffix"]
            cid = attachment["cid"]
            content = attachment["content"]
            inline = attachment["inline"]
            try:
                if attachment.get("readError"):
                    raise RuntimeError(attachment["readError"])
                url = self._upload(filename, content)
                # Upload and OCR are independent. Keep the public URL even when
                # the OCR service is unavailable or returns an invalid response.
                ocr = ""
                if suffix in IMAGE_EXTENSIONS:
                    try:
                        ocr = self._ocr(filename, content)
                    except Exception:
                        logger.warning("email attachment OCR failed name=%s", filename,
                                       exc_info=True)
                alt = ocr.strip().replace("\r", " ").replace("\n", " ")
                alt = alt.replace("[", "\\[").replace("]", "\\]")
                label = alt or filename
                value = f"![{label}]({url})" if suffix in IMAGE_EXTENSIONS else f"[{filename}]({url})"
                if inline:
                    html_body = re.sub(
                        rf"cid:{re.escape(cid)}", url, html_body, flags=re.I)
                    html_body = re.sub(
                        rf"(<img\b[^>]*src=[\"']{re.escape(url)}[\"'][^>]*)(>)",
                        lambda match: self._with_alt(match, alt), html_body, flags=re.I)
                else:
                    markdown.append(value)
                rows.append({"name": filename, "url": url, "ocr": ocr,
                             "inline": inline})
            except Exception as exc:
                logger.warning("email attachment failed name=%s", filename, exc_info=True)
                markdown.append(
                    f"![OCR结果](无法显示图片：{filename})")
                rows.append({"name": filename, "url": "", "ocr": "",
                             "inline": False, "error": str(exc)})
        return html_body, markdown, rows

    @staticmethod
    def _with_alt(match, alt: str) -> str:
        prefix = re.sub(r"\s+alt=[\"'][^\"']*[\"']", "", match.group(1), flags=re.I)
        escaped = html.escape(alt, quote=True)
        return f'{prefix} alt="{escaped}"{match.group(2)}'

    def _upload(self, filename: str, content: bytes) -> str:
        response = requests.post(
            self.settings.image_file_server_url,
            files={"file": (filename, content)}, timeout=60, verify=False)
        response.raise_for_status()
        try:
            body = response.json()
            url = body.get("url") if isinstance(body, dict) else ""
        except ValueError as exc:
            raise RuntimeError("image upload response is not JSON") from exc
        if not url:
            raise RuntimeError("image upload response did not contain url")
        return str(url)

    def _ocr(self, filename: str, content: bytes) -> str:
        if not self.settings.ocr_url:
            return ""
        response = requests.post(
            self.settings.ocr_url, files={"file": (filename, content)},
            timeout=300, verify=False)
        response.raise_for_status()
        body = response.json()
        return str(body.get("result") or body.get("text") or "") \
            if isinstance(body, dict) else str(body)

    @staticmethod
    def _email_markdown(summary: dict, body: str, attachments: list[str]) -> str:
        lines = [
            f"# {summary.get('subject') or '无主题邮件'}",
            "",
            f"- 邮件 ID：{summary.get('id') or ''}",
            f"- 发件人：{summary.get('senderName') or ''} <{summary.get('senderEmail') or ''}>",
            f"- 接收时间：{summary.get('receivedTime') or ''}",
            f"- 会话主题：{summary.get('conversationTopic') or ''}",
            "", "## 正文", "", body.strip(),
        ]
        if attachments:
            lines.extend(["", "## 附件", "", *attachments])
        return "\n".join(lines).strip() + "\n"
