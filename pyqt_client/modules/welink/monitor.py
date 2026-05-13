"""WeLink 群聊录制监听线程"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal


def _app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


_STATE_FILE   = _app_dir() / '.welink_last_ids.json'
_SESSION_FILE = _app_dir() / '.welink_sessions.json'


class WelinkMonitor(QThread):
    log_signal      = pyqtSignal(str)
    uploaded_signal = pyqtSignal(dict)   # {group_name, chat_id, count}

    def __init__(self, bot_name: str, user_id: str, poll_interval: int, backend_base: str):
        super().__init__()
        self._bot_name      = bot_name
        self._user_id       = user_id
        self._poll_interval = max(1, poll_interval)
        self._backend_base  = backend_base
        self._running       = False

        # {group_id: last_seen_msg_id (int)}
        self._last_ids: dict = self._load_json(_STATE_FILE, {})
        # {group_id: {start_msg_id, start_time, group_name}}
        self._recording: dict = self._load_json(_SESSION_FILE, {})

    # ── public ────────────────────────────────────────────────────

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        self._log('WeLink 监听已启动')
        while self._running:
            try:
                self._poll()
            except Exception as e:
                self._log(f'轮询异常: {e}')
            time.sleep(self._poll_interval)
        self._log('WeLink 监听已停止')

    # ── poll ──────────────────────────────────────────────────────

    def _poll(self):
        convs = self._get_conversations()
        for conv in convs:
            if conv.get('recent_conversation_type') != 'CHAT_TYPE_GROUP_MSG':
                continue
            group_id   = str(conv.get('group_id', ''))
            group_name = conv.get('group_name') or group_id
            if not group_id:
                continue
            self._check_group(group_id, group_name)

    def _check_group(self, group_id: str, group_name: str):
        msgs = self._get_messages(group_id, 20)
        if not msgs:
            return

        last_seen = self._last_ids.get(group_id)

        # messages come newest-first; reverse to process chronologically
        for msg in reversed(msgs):
            msg_id = msg.get('msgId')
            if msg_id is None:
                continue
            msg_id = int(msg_id)

            if last_seen is None:
                # first time seeing this group — just bookmark, don't process history
                self._last_ids[group_id] = msg_id
                self._save_json(_STATE_FILE, self._last_ids)
                return

            if msg_id <= last_seen:
                continue

            # new message
            self._handle_msg(group_id, group_name, msg)
            self._last_ids[group_id] = msg_id
            self._save_json(_STATE_FILE, self._last_ids)

    def _handle_msg(self, group_id: str, group_name: str, msg: dict):
        content = msg.get('content', '')
        bot     = re.escape(self._bot_name)
        start_re = re.compile(rf'@{bot}\s+开始问题记录')
        end_re   = re.compile(rf'@{bot}\s+结束问题记录')

        if start_re.search(content):
            msg_id    = int(msg['msgId'])
            send_time = msg.get('serverSendTime', 0)
            self._recording[group_id] = {
                'start_msg_id': msg_id,
                'start_time':   send_time,
                'group_name':   group_name,
            }
            self._save_json(_SESSION_FILE, self._recording)
            self._log(f'[{group_name}] 开始录制 (msgId={msg_id})')

        elif end_re.search(content) and group_id in self._recording:
            rec        = self._recording.pop(group_id)
            self._save_json(_SESSION_FILE, self._recording)
            end_msg_id = int(msg['msgId'])
            end_time   = msg.get('serverSendTime', 0)
            self._log(f'[{group_name}] 结束录制，正在抓取消息...')
            self._finish_recording(group_id, group_name, rec, end_msg_id, end_time)

    # ── finish ────────────────────────────────────────────────────

    def _finish_recording(self, group_id: str, group_name: str,
                          rec: dict, end_msg_id: int, end_time: int):
        start_msg_id = rec['start_msg_id']
        start_time   = rec['start_time']

        all_msgs = self._get_messages(group_id, 200)
        if not all_msgs:
            self._log(f'[{group_name}] 无法获取消息，放弃上传')
            return

        in_range = [
            m for m in all_msgs
            if start_msg_id <= int(m.get('msgId', 0)) <= end_msg_id
        ]
        in_range.sort(key=lambda m: m.get('serverSendTime', 0))

        html_body = _msgs_to_html(in_range, group_name, start_time, end_time)
        chat_id   = f"{group_id}_{start_msg_id}"

        payload = {
            'ChatId':    chat_id,
            'GroupId':   group_id,
            'GroupName': group_name,
            'StartTime': start_time,
            'EndTime':   end_time,
            'HtmlBody':  html_body,
            'UploadBy':  self._user_id,
        }

        try:
            import requests, urllib3
            urllib3.disable_warnings()
            r = requests.post(
                f'{self._backend_base}/api/welink/receive',
                json=payload, timeout=60, verify=False,
            )
            r.raise_for_status()
            result = r.json()
            if result.get('Duplicate'):
                self._log(f'[{group_name}] 已存在，跳过 ({chat_id})')
            else:
                self._log(f'[{group_name}] 上传成功 ({len(in_range)} 条消息)')
            self.uploaded_signal.emit({
                'group_name': group_name,
                'chat_id':    chat_id,
                'count':      len(in_range),
                'duplicate':  result.get('Duplicate', False),
            })
        except Exception as e:
            self._log(f'[{group_name}] 上传失败: {e}')

    # ── welink-cli helpers ────────────────────────────────────────

    def _run_cli(self, args: list):
        try:
            r = subprocess.run(
                ['welink-cli'] + args,
                capture_output=True, text=True,
                encoding='utf-8', errors='ignore', timeout=30,
            )
            return json.loads(r.stdout)
        except Exception:
            return None

    def _get_conversations(self) -> list:
        d = self._run_cli(['im', 'query-recent-conversation', '--count', '20'])
        if d:
            return d.get('conversation_info', [])
        return []

    def _get_messages(self, group_id: str, count: int = 20) -> list:
        d = self._run_cli([
            'im', 'query-history-message',
            '--group-id', group_id,
            '--query-count', str(count),
        ])
        if d and d.get('resultCode') == '0':
            return d.get('respData', {}).get('chatInfo', [])
        return []

    # ── persistence ───────────────────────────────────────────────

    @staticmethod
    def _load_json(path: Path, default):
        try:
            if path.exists():
                return json.loads(path.read_text('utf-8'))
        except Exception:
            pass
        return default

    @staticmethod
    def _save_json(path: Path, obj):
        try:
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), 'utf-8')
        except Exception:
            pass

    def _log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.log_signal.emit(f'[{ts}] {msg}')


# ── HTML rendering ────────────────────────────────────────────────

def _msgs_to_html(msgs: list, group_name: str, start_ts: int, end_ts: int) -> str:
    def fmt_ts(ms):
        if not ms:
            return ''
        return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S')

    header = (
        f'<h2 style="margin:0 0 4px">群聊记录 — {escape(group_name)}</h2>'
        f'<p style="color:#888;font-size:12px;margin:0 0 12px">'
        f'{fmt_ts(start_ts)} ~ {fmt_ts(end_ts)}'
        f'</p>'
    )

    rows = []
    for m in msgs:
        sender       = escape(m.get('sender', ''))
        content_type = m.get('contentType', '')
        raw          = m.get('content', '')
        ts_ms        = m.get('serverSendTime', 0)
        t            = fmt_ts(ts_ms)

        if content_type == 'PICTURE_MSG':
            body = '<em>[图片]</em>'
        elif content_type == 'FILE_MSG':
            body = '<em>[文件]</em>'
        elif content_type == 'CARD_MSG':
            body = '<em>[卡片消息]</em>'
        elif content_type == 'NOTICE_MSG':
            body = f'<em>[系统通知] {escape(raw)}</em>'
        else:
            # TEXT_MSG — may contain HTML from bot replies; sanitise lightly
            body = raw if raw.strip().startswith('<') else escape(raw).replace('\n', '<br>')

        rows.append(
            f'<div style="margin:6px 0;padding:6px 10px;background:#f5f5f5;border-radius:4px;">'
            f'<span style="font-weight:bold;color:#1a73e8">{sender}</span>'
            f'<span style="font-size:11px;color:#aaa;margin-left:8px">{t}</span>'
            f'<div style="margin-top:4px">{body}</div>'
            f'</div>'
        )

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>body{font-family:Arial,sans-serif;font-size:13px;color:#222;'
        'max-width:860px;margin:20px auto;padding:0 16px}</style>'
        '</head><body>'
        + header
        + ''.join(rows)
        + '</body></html>'
    )
