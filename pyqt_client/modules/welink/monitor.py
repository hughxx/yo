"""WeLink 群聊录制监听线程"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

from PyQt5.QtCore import QThread, pyqtSignal


def _app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


_STATE_FILE   = _app_dir() / '.welink_last_ids.json'
_SESSION_FILE = _app_dir() / '.welink_sessions.json'

# Windows 下隐藏 subprocess 弹出的黑框
_STARTUPINFO = None
if sys.platform == 'win32':
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW


def _run_cli(args: list):
    """返回 (parsed_json_or_None, error_str_or_None)"""
    try:
        r = subprocess.run(
            ['welink-cli'] + args,
            capture_output=True, text=True,
            encoding='utf-8', errors='ignore',
            timeout=30,
            startupinfo=_STARTUPINFO,
        )
        return json.loads(r.stdout), None
    except json.JSONDecodeError as e:
        return None, f'JSON解析失败: {e}'
    except Exception as e:
        return None, str(e)


def _get_messages(group_id: str, count: int = 20):
    """返回 (messages: list, error: str | None)"""
    d, err = _run_cli(['im', 'query-history-message',
                       '--group-id', group_id, '--query-count', str(count)])
    if err:
        return [], err
    if not d:
        return [], 'CLI 无返回'
    if d.get('resultCode') != '0':
        return [], f'resultCode={d.get("resultCode")} context={d.get("resultContext", "")}'
    return d.get('respData', {}).get('chatInfo', []), None


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text('utf-8'))
    except Exception:
        pass
    return default


def _save(path: Path, obj):
    try:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), 'utf-8')
    except Exception:
        pass


def _parse_um_content(content: str):
    """解析 /:um_begin{URL|Type|Size|FileName|0|W;H;extraction_code|...}/:um_end
    返回 (download_url, file_name, extraction_code) 或 (None, None, None)"""
    prefix, suffix = '/:um_begin{', '}/:um_end'
    if not (content.startswith(prefix) and content.endswith(suffix)):
        return None, None, None
    inner = content[len(prefix):-len(suffix)]
    parts = inner.split('|')
    if len(parts) < 6:
        return None, None, None
    download_url = parts[0]
    file_name    = parts[3]
    field5       = parts[5].split(';')
    extraction_code = field5[2] if len(field5) > 2 else ''
    return download_url, file_name, extraction_code


def _one_box_download(download_url: str, extraction_code: str):
    """从 onebox/clouddrive 下载文件，返回 bytes 或 None"""
    try:
        r = requests.get(download_url,
                         params={'extractionCode': extraction_code},
                         timeout=30, verify=False)
        if r.ok and r.content:
            return r.content
    except Exception:
        pass
    return None


def _msgs_to_html(msgs: list, group_name: str, start_ts: int, end_ts: int) -> str:
    def fmt(ms):
        return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S') if ms else ''

    rows = []
    for m in msgs:
        sender = escape(m.get('sender', ''))
        ct     = m.get('contentType', '')
        raw    = m.get('content', '')
        t      = fmt(m.get('serverSendTime', 0))

        if ct in ('PICTURE_MSG', 'FILE_MSG'):
            img_url  = m.get('_img_url')
            img_name = escape(m.get('_img_name', ''))
            if ct == 'PICTURE_MSG' and img_url:
                body = (f'<img src="{img_url}" style="max-width:480px;display:block">'
                        f'<small style="color:#888">{img_name}</small>')
            elif ct == 'FILE_MSG' and img_url:
                body = f'<a href="{img_url}">[文件] {img_name}</a>'
            else:
                body = f'<em>[{"图片" if ct == "PICTURE_MSG" else "文件"}] {img_name}</em>'
        elif ct == 'CARD_MSG':
            body = '<em>[卡片消息]</em>'
        elif ct == 'NOTICE_MSG':
            body = f'<em>[系统通知] {escape(raw)}</em>'
        else:
            body = raw if raw.strip().startswith('<') else escape(raw).replace('\n', '<br>')

        rows.append(
            f'<div style="margin:6px 0;padding:6px 10px;background:#f5f5f5;border-radius:4px;">'
            f'<span style="font-weight:bold;color:#1a73e8">{sender}</span>'
            f'<span style="font-size:11px;color:#aaa;margin-left:8px">{t}</span>'
            f'<div style="margin-top:4px">{body}</div></div>'
        )

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>body{font-family:Arial,sans-serif;font-size:13px;color:#222;'
        'max-width:860px;margin:20px auto;padding:0 16px}</style></head><body>'
        f'<h2 style="margin:0 0 4px">群聊记录 — {escape(group_name)}</h2>'
        f'<p style="color:#888;font-size:12px;margin:0 0 12px">'
        f'{fmt(start_ts)} ~ {fmt(end_ts)}</p>'
        + ''.join(rows)
        + '</body></html>'
    )


class WelinkMonitor(QThread):
    log_signal      = pyqtSignal(str)
    uploaded_signal = pyqtSignal(dict)

    def __init__(self, backend_base: str, bot_name: str, user_id: str, poll_interval: int = 3):
        super().__init__()
        self._backend_base  = backend_base.rstrip('/')
        self._bot_name      = bot_name
        self._user_id       = user_id
        self._poll_interval = max(1, poll_interval)
        self._running       = False

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        self._log('WeLink 监听已启动')

        last_ids:  dict = _load(_STATE_FILE, {})
        recording: dict = _load(_SESSION_FILE, {})

        start_re = re.compile(rf'@{re.escape(self._bot_name)}\s+开始问题记录')
        end_re   = re.compile(rf'@{re.escape(self._bot_name)}\s+结束问题记录')

        rules_cache: list = []
        rules_ts = 0.0

        while self._running:
            try:
                now = time.time()
                if now - rules_ts > 60:
                    rules_cache = self._fetch_rules()
                    rules_ts    = now

                for rule in rules_cache:
                    if not self._running:
                        break
                    group_id   = str(rule['group_id'])
                    group_name = rule.get('group_name') or group_id

                    msgs, err = _get_messages(group_id, 20)
                    if err:
                        self._log(f'[{group_name}] 拉取消息失败: {err}')
                        continue

                    last_seen = last_ids.get(group_id)

                    for msg in reversed(msgs):  # oldest first
                        msg_id = msg.get('msgId')
                        if msg_id is None:
                            continue
                        msg_id = int(msg_id)

                        if last_seen is None:
                            last_ids[group_id] = msg_id
                            _save(_STATE_FILE, last_ids)
                            break

                        if msg_id <= last_seen:
                            continue

                        content = msg.get('content', '')

                        if start_re.search(content):
                            recording[group_id] = {
                                'start_msg_id': msg_id,
                                'start_time':   msg.get('serverSendTime', 0),
                                'group_name':   group_name,
                            }
                            _save(_SESSION_FILE, recording)
                            self._log(f'[{group_name}] 开始录制 (msgId={msg_id})')

                        elif end_re.search(content) and group_id in recording:
                            rec = recording.pop(group_id)
                            _save(_SESSION_FILE, recording)
                            self._log(f'[{group_name}] 结束录制，正在上传…')
                            self._finish(group_id, group_name, rec,
                                         msg_id, msg.get('serverSendTime', 0))

                        last_ids[group_id] = msg_id
                        _save(_STATE_FILE, last_ids)

            except Exception as e:
                self._log(f'轮询异常: {e}')

            time.sleep(self._poll_interval)

        self._log('WeLink 监听已停止')

    # ── finish recording ──────────────────────────────────────────

    def _finish(self, group_id: str, group_name: str, rec: dict,
                end_msg_id: int, end_time: int):
        start_msg_id = rec['start_msg_id']
        start_time   = rec['start_time']

        # welink-cli 单次最多支持 100 条，分两次取保险
        all_msgs, err = _get_messages(group_id, 100)
        if err:
            self._log(f'[{group_name}] 获取消息失败: {err}，放弃上传')
            return
        if not all_msgs:
            self._log(f'[{group_name}] 获取到 0 条消息，放弃上传')
            return

        in_range = [
            m for m in all_msgs
            if start_msg_id <= int(m.get('msgId', 0)) <= end_msg_id
        ]
        in_range.sort(key=lambda m: m.get('serverSendTime', 0))

        self._log(f'[{group_name}] 共拉取 {len(all_msgs)} 条，范围内 {len(in_range)} 条')

        # 下载图片/文件并上传到后端，写入 _img_url 供 HTML 渲染使用
        for m in in_range:
            ct = m.get('contentType', '')
            if ct in ('PICTURE_MSG', 'FILE_MSG'):
                raw = m.get('content', '')
                dl_url, fname, extraction_code = _parse_um_content(raw)
                if dl_url and fname:
                    m['_img_name'] = fname
                    file_bytes = _one_box_download(dl_url, extraction_code)
                    if file_bytes:
                        public_url = self._upload_image(file_bytes, fname)
                        if public_url:
                            m['_img_url'] = public_url
                        else:
                            self._log(f'  图片上传失败: {fname}')
                    else:
                        self._log(f'  图片下载失败: {fname} ({dl_url[:60]})')

        html_body = _msgs_to_html(in_range, group_name, start_time, end_time)
        chat_id   = f'{group_id}_{start_msg_id}'

        try:
            r = requests.post(
                f'{self._backend_base}/api/welink/receive',
                json={
                    'ChatId':    chat_id,
                    'GroupId':   group_id,
                    'GroupName': group_name,
                    'StartTime': start_time,
                    'EndTime':   end_time,
                    'HtmlBody':  html_body,
                    'UploadBy':  self._user_id,
                },
                timeout=60, verify=False,
            )
            r.raise_for_status()
            result = r.json()
            dup = result.get('Duplicate', False)
            if dup:
                self._log(f'[{group_name}] 已存在，跳过')
            else:
                self._log(f'[{group_name}] 上传成功 ({len(in_range)} 条)')
            self.uploaded_signal.emit({
                'group_name': group_name,
                'chat_id':    chat_id,
                'count':      len(in_range),
                'duplicate':  dup,
            })
        except Exception as e:
            self._log(f'[{group_name}] 上传失败: {e}')

    # ── helpers ───────────────────────────────────────────────────

    def _upload_image(self, file_bytes: bytes, file_name: str):
        """上传图片到后端，返回公开 URL 或 None"""
        try:
            r = requests.post(
                f'{self._backend_base}/api/email/upload_image',
                files={'file': (file_name, file_bytes)},
                data={'filename': file_name},
                timeout=30, verify=False,
            )
            r.raise_for_status()
            return r.json().get('Url')
        except Exception:
            return None

    def _fetch_rules(self) -> list:
        try:
            r = requests.get(f'{self._backend_base}/api/welink/rules',
                             timeout=10, verify=False)
            r.raise_for_status()
            return [row for row in r.json() if row.get('enabled', True)]
        except Exception:
            return []

    def _log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.log_signal.emit(f'[{ts}] {msg}')
