"""WeLink 群聊录制监听线程"""
import json
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


def _normalize(text: str) -> str:
    """WeLink @提及后跟的 Unicode 空格（如 ）归一化为普通空格。"""
    for cp in (
        ' ', ' ', ' ', ' ', ' ', ' ',
        ' ', ' ', ' ', ' ', ' ', ' ',
        ' ', ' ', ' ', '　',
    ):
        text = text.replace(cp, ' ')
    return text



def _parse_summary_cmd(prefix: str, norm: str):
    """解析 '<prefix> 用户名 工号 YYYY-MM-DD HH:MM [YYYY-MM-DD HH:MM]'
    返回 (username, employee_id, start_dt, end_dt_or_None) 或 None。"""
    if prefix not in norm:
        return None
    rest = norm[norm.index(prefix) + len(prefix):].strip()
    parts = rest.split()
    if len(parts) < 4:
        return None
    try:
        start_dt = datetime.strptime(f'{parts[2]} {parts[3]}', '%Y-%m-%d %H:%M')
        end_dt = None
        if len(parts) >= 6:
            end_dt = datetime.strptime(f'{parts[4]} {parts[5]}', '%Y-%m-%d %H:%M')
        return parts[0], parts[1], start_dt, end_dt
    except ValueError:
        return None


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


def _msgs_to_html(msgs: list) -> str:
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
        + ''.join(rows)
        + '</body></html>'
    )


class WelinkMonitor(QThread):
    log_signal      = pyqtSignal(str)
    uploaded_signal = pyqtSignal(dict)

    def __init__(self, backend_base: str, start_cmd: str, end_cmd: str,
                 summary_cmd: str, user_id: str, poll_interval: int = 3):
        super().__init__()
        self._backend_base  = backend_base.rstrip('/')
        self._start_cmd     = start_cmd
        self._end_cmd       = end_cmd
        self._summary_cmd   = summary_cmd
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

        rules_cache: list = []
        rules_ts = 0.0

        while self._running:
            try:
                now = time.time()
                if now - rules_ts > 60:
                    rules_cache = self._fetch_rules()
                    rules_ts    = now
                    if rules_cache:
                        names = ', '.join(r.get('group_name') or r['group_id'] for r in rules_cache)
                        self._log(f'已加载 {len(rules_cache)} 条规则: {names}')
                    else:
                        self._log('未找到启用的群聊规则，请在规则列表中添加')

                for rule in rules_cache:
                    if not self._running:
                        break
                    group_id   = str(rule['group_id'])
                    group_name = rule.get('group_name') or group_id

                    msgs, err = _get_messages(group_id, 20)
                    if err:
                        self._log(f'[{group_name}] 拉取消息失败: {err}')
                        continue
                    if not msgs:
                        self._log(f'[{group_name}] CLI 返回 0 条消息')
                        continue

                    last_seen = last_ids.get(group_id)
                    new_count = sum(1 for m in msgs if m.get('msgId') and int(m['msgId']) > (last_seen or 0))
                    self._log(f'[{group_name}] 拉取 {len(msgs)} 条，last_seen={last_seen}，新消息 {new_count} 条')

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
                        norm = _normalize(content)

                        if self._start_cmd in norm:
                            recording[group_id] = {
                                'start_msg_id': msg_id,
                                'start_time':   msg.get('serverSendTime', 0),
                                'group_name':   group_name,
                            }
                            _save(_SESSION_FILE, recording)
                            self._log(f'[{group_name}] 开始录制 (msgId={msg_id})')

                        elif self._end_cmd in norm and group_id in recording:
                            rec = recording.pop(group_id)
                            _save(_SESSION_FILE, recording)
                            self._log(f'[{group_name}] 结束录制，正在上传…')
                            self._finish(group_id, group_name, rec,
                                         msg_id, msg.get('serverSendTime', 0))

                        elif self._summary_cmd and self._summary_cmd in norm:
                            parsed = _parse_summary_cmd(self._summary_cmd, norm)
                            if parsed:
                                username, employee_id, start_dt, end_dt = parsed
                                self._log(f'[{group_name}] 收到总结命令，定位起始消息…')
                                self._finish_summary(
                                    group_id, group_name,
                                    msg_id, msg.get('serverSendTime', 0),
                                    username, employee_id, start_dt, end_dt,
                                )
                            else:
                                self._log(f'[{group_name}] 总结命令格式错误，期望: {self._summary_cmd} 用户名 工号 YYYY-MM-DD HH:MM [YYYY-MM-DD HH:MM]')

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
        self._enrich_images(in_range, group_name)

        chat_id = f'{group_id}_{start_msg_id}'
        self._upload_chatlog(chat_id, group_id, group_name,
                             start_time, end_time, in_range)

    # ── finish summary ────────────────────────────────────────────

    def _finish_summary(self, group_id: str, group_name: str,
                        summary_msg_id: int, summary_time: int,
                        username: str, employee_id: str,
                        start_dt: datetime, end_dt: datetime | None):
        all_msgs, err = _get_messages(group_id, 100)
        if err or not all_msgs:
            self._log(f'[{group_name}] 获取消息失败: {err}，放弃总结')
            return

        # 找起始消息：sender 匹配 username 或 employee_id，时间戳在指定分钟内
        start_ms = int(start_dt.timestamp() * 1000)

        start_msg = None
        for m in sorted(all_msgs, key=lambda x: x.get('serverSendTime', 0)):
            sender    = m.get('sender', '')
            send_time = m.get('serverSendTime', 0)
            if start_ms <= send_time < start_ms + 60_000 and sender in (username, employee_id):
                start_msg = m
                break

        if start_msg is None:
            self._log(
                f'[{group_name}] 未找到 {username}/{employee_id} 在 {start_dt.strftime("%H:%M")} 的起始消息'
            )
            return

        start_msg_id = int(start_msg.get('msgId', 0))

        if end_dt is not None:
            # 指定了结束时间：截到该时间戳所在分钟结束
            end_ms = int(end_dt.timestamp() * 1000) + 60_000
            in_range = [
                m for m in all_msgs
                if start_msg_id <= int(m.get('msgId', 0))
                and m.get('serverSendTime', 0) < end_ms
            ]
            actual_end_time = int(end_dt.timestamp() * 1000)
        else:
            # 未指定结束时间：截到总结命令前一条
            in_range = [
                m for m in all_msgs
                if start_msg_id <= int(m.get('msgId', 0)) < summary_msg_id
            ]
            actual_end_time = summary_time

        in_range.sort(key=lambda m: m.get('serverSendTime', 0))
        self._log(f'[{group_name}] 总结范围 {len(in_range)} 条，正在上传…')
        self._enrich_images(in_range, group_name)

        chat_id = f'{group_id}_{start_msg_id}_s'
        self._upload_chatlog(chat_id, group_id, group_name,
                             start_msg.get('serverSendTime', 0), actual_end_time, in_range)

    # ── helpers ───────────────────────────────────────────────────

    def _enrich_images(self, msgs: list, group_name: str):
        """下载图片/文件并上传到后端，写入 _img_url 供 HTML 渲染使用。"""
        for m in msgs:
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

    def _upload_chatlog(self, chat_id: str, group_id: str, group_name: str,
                        start_time: int, end_time: int, msgs: list):
        html_body = _msgs_to_html(msgs)
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
                self._log(f'[{group_name}] 上传成功 ({len(msgs)} 条)')
            self.uploaded_signal.emit({
                'group_name': group_name,
                'chat_id':    chat_id,
                'count':      len(msgs),
                'duplicate':  dup,
            })
        except Exception as e:
            self._log(f'[{group_name}] 上传失败: {e}')

    def _upload_image(self, file_bytes: bytes, file_name: str):
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
        except Exception as e:
            self._log(f'获取规则失败: {e}')
            return []

    def _log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.log_signal.emit(f'[{ts}] {msg}')
