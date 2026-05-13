"""
WeLink 群聊录制监听脚本
========================
配置区修改好后直接运行即可，无需保持 PyQt 客户端开启。
群聊监听规则（哪些群要录制）在 PyQt 客户端的 WeLink 页面配置。

触发方式：
  @{BOT_NAME} 开始问题记录  →  开始录制
  @{BOT_NAME} 结束问题记录  →  结束录制

运行：
  python welink_monitor.py
"""

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

# ==================== ★ 配置区 ★ ====================

BACKEND_URL   = "http://localhost:8023"   # 后端地址
BOT_NAME      = "云见"                    # 机器人名称（@ 触发词）
USER_ID       = ""                         # 上传者工号（upload_by）
POLL_INTERVAL = 3                          # 轮询间隔（秒）

# =====================================================

_SCRIPT_DIR   = Path(__file__).parent
_STATE_FILE   = _SCRIPT_DIR / '.welink_last_ids.json'
_SESSION_FILE = _SCRIPT_DIR / '.welink_sessions.json'

# Windows 下隐藏 subprocess 弹出的黑框
_STARTUPINFO = None
if sys.platform == 'win32':
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW


# ── CLI helpers ───────────────────────────────────────────────────

def _run_cli(args: list):
    try:
        r = subprocess.run(
            ['welink-cli'] + args,
            capture_output=True, text=True,
            encoding='utf-8', errors='ignore',
            timeout=30,
            startupinfo=_STARTUPINFO,
        )
        return json.loads(r.stdout)
    except Exception:
        return None


def get_messages(group_id: str, count: int = 20) -> list:
    d = _run_cli(['im', 'query-history-message',
                  '--group-id', group_id, '--query-count', str(count)])
    if d and d.get('resultCode') == '0':
        return d.get('respData', {}).get('chatInfo', [])
    return []


# ── backend helpers ───────────────────────────────────────────────

def fetch_rules() -> list:
    """从后端获取启用的群聊规则列表。"""
    try:
        r = requests.get(f'{BACKEND_URL}/api/welink/rules', timeout=10, verify=False)
        r.raise_for_status()
        return [row for row in r.json() if row.get('enabled', True)]
    except Exception as e:
        log(f'获取规则失败: {e}')
        return []


def upload_chatlog(payload: dict) -> dict:
    r = requests.post(f'{BACKEND_URL}/api/welink/receive',
                      json=payload, timeout=60, verify=False)
    r.raise_for_status()
    return r.json()


# ── state persistence ─────────────────────────────────────────────

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


# ── HTML rendering ────────────────────────────────────────────────

def msgs_to_html(msgs: list, group_name: str, start_ts: int, end_ts: int) -> str:
    def fmt(ms):
        return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S') if ms else ''

    rows = []
    for m in msgs:
        sender = escape(m.get('sender', ''))
        ct     = m.get('contentType', '')
        raw    = m.get('content', '')
        t      = fmt(m.get('serverSendTime', 0))

        if ct == 'PICTURE_MSG':
            body = '<em>[图片]</em>'
        elif ct == 'FILE_MSG':
            body = '<em>[文件]</em>'
        elif ct == 'CARD_MSG':
            body = '<em>[卡片消息]</em>'
        elif ct == 'NOTICE_MSG':
            body = f'<em>[系统通知] {escape(raw)}</em>'
        else:
            body = raw if raw.strip().startswith('<') else escape(raw).replace('\n', '<br>')

        rows.append(
            f'<div style="margin:6px 0;padding:6px 10px;'
            f'background:#f5f5f5;border-radius:4px;">'
            f'<span style="font-weight:bold;color:#1a73e8">{sender}</span>'
            f'<span style="font-size:11px;color:#aaa;margin-left:8px">{t}</span>'
            f'<div style="margin-top:4px">{body}</div></div>'
        )

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>body{font-family:Arial,sans-serif;font-size:13px;color:#222;'
        'max-width:860px;margin:20px auto;padding:0 16px}</style></head><body>'
        f'<h2 style="margin:0 0 4px">群聊记录 — {escape(group_name)}</h2>'
        f'<p style="color:#888;font-size:12px;margin:0 0 12px">{fmt(start_ts)} ~ {fmt(end_ts)}</p>'
        + ''.join(rows)
        + '</body></html>'
    )


# ── log ───────────────────────────────────────────────────────────

def log(msg: str):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}', flush=True)


# ── core loop ─────────────────────────────────────────────────────

def main():
    log(f'WeLink 监听启动 — 机器人: @{BOT_NAME}  上传者: {USER_ID or "（未设置）"}')
    log(f'后端: {BACKEND_URL}  轮询间隔: {POLL_INTERVAL}s')
    log('按 Ctrl+C 停止')
    log('-' * 50)

    last_ids:   dict = _load(_STATE_FILE, {})    # {group_id: last_seen_msg_id}
    recording:  dict = _load(_SESSION_FILE, {})  # {group_id: {start_msg_id, start_time, group_name}}

    start_re = re.compile(rf'@{re.escape(BOT_NAME)}\s+开始问题记录')
    end_re   = re.compile(rf'@{re.escape(BOT_NAME)}\s+结束问题记录')

    # refresh rules every 60 s to pick up changes without restart
    rules_cache: list = []
    rules_ts = 0

    while True:
        try:
            now = time.time()
            if now - rules_ts > 60:
                rules_cache = fetch_rules()
                rules_ts    = now
                if rules_cache:
                    names = ', '.join(r.get('group_name') or r['group_id'] for r in rules_cache)
                    log(f'监听 {len(rules_cache)} 个群聊: {names}')
                else:
                    log('暂无监听规则，请在客户端添加群聊')

            for rule in rules_cache:
                group_id   = str(rule['group_id'])
                group_name = rule.get('group_name') or group_id

                msgs = get_messages(group_id, 20)
                if not msgs:
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
                        break  # initialise this group, skip history

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
                        log(f'[{group_name}] 开始录制 (msgId={msg_id})')

                    elif end_re.search(content) and group_id in recording:
                        rec        = recording.pop(group_id)
                        _save(_SESSION_FILE, recording)
                        end_msg_id = msg_id
                        end_time   = msg.get('serverSendTime', 0)
                        log(f'[{group_name}] 结束录制，抓取消息中…')
                        _finish(group_id, group_name, rec, end_msg_id, end_time,
                                start_re, end_re)

                    last_ids[group_id] = msg_id
                    _save(_STATE_FILE, last_ids)

        except KeyboardInterrupt:
            log('已停止')
            sys.exit(0)
        except Exception as e:
            log(f'错误: {e}')

        time.sleep(POLL_INTERVAL)


def _finish(group_id: str, group_name: str, rec: dict,
            end_msg_id: int, end_time: int, start_re, end_re):
    start_msg_id = rec['start_msg_id']
    start_time   = rec['start_time']

    all_msgs = get_messages(group_id, 200)
    if not all_msgs:
        log(f'[{group_name}] 获取消息失败，放弃上传')
        return

    in_range = [
        m for m in all_msgs
        if start_msg_id <= int(m.get('msgId', 0)) <= end_msg_id
    ]
    in_range.sort(key=lambda m: m.get('serverSendTime', 0))

    html_body = msgs_to_html(in_range, group_name, start_time, end_time)
    chat_id   = f'{group_id}_{start_msg_id}'

    payload = {
        'ChatId':    chat_id,
        'GroupId':   group_id,
        'GroupName': group_name,
        'StartTime': start_time,
        'EndTime':   end_time,
        'HtmlBody':  html_body,
        'UploadBy':  USER_ID,
    }

    try:
        result = upload_chatlog(payload)
        if result.get('Duplicate'):
            log(f'[{group_name}] 已存在，跳过 ({chat_id})')
        else:
            log(f'[{group_name}] 上传成功 ({len(in_range)} 条消息) chat_id={chat_id}')
    except Exception as e:
        log(f'[{group_name}] 上传失败: {e}')


if __name__ == '__main__':
    main()
