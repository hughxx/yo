"""自动回复监听线程，逻辑参考 welink_usage.txt，AI 调用替换为本地后端。"""
import json
import re
import subprocess
import time
import unicodedata

import sys

import requests
from PyQt5.QtCore import QThread, pyqtSignal

_STARTUPINFO = None
if sys.platform == 'win32':
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW

NON_QUESTION_PATTERNS = [
    "嗯", "嗯嗯", "嗯嗯嗯", "好的", "好滴", "收到", "知道了", "明白",
    "OK", "ok", "好的嘞", "好嘞", "哦", "哦哦", "哈哈", "hhh",
    "666", "太强了", "棒", "谢谢", "感谢", "好的呀", "好呀",
    "笑死", "笑死了", "哇塞", "厉害", "牛", "牛啊",
    "赞", "点赞", "优秀", "6666", "可以的", "行", "okk", "收到啦", "好哒",
]

_UNICODE_SPACES = re.compile(r'[ -​　\xa0]')


def _norm(text: str) -> str:
    return _UNICODE_SPACES.sub(' ', unicodedata.normalize('NFKC', text))


def _is_question(content: str) -> bool:
    c = content.strip().lower()
    for p in NON_QUESTION_PATTERNS:
        if c == p or c.startswith(p + ' ') or c.endswith(' ' + p):
            return False
    return True


def _run_cli(*args) -> dict:
    cmd = ['welink-cli', 'im'] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=15, encoding='utf-8', errors='ignore',
                                startupinfo=_STARTUPINFO)
        return json.loads(result.stdout or '{}')
    except Exception:
        return {}


class AutoReplyMonitor(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, prompt: str, bot_id: str, backend_base: str,
                 poll_interval: int = 5, parent=None):
        super().__init__(parent)
        self._prompt    = prompt
        self._bot_id    = bot_id.strip()
        self._backend   = backend_base.rstrip('/')
        self._interval  = poll_interval
        self._running   = False
        self._last_ids  = {}   # account / "g:{group_id}" -> last seen msgId

    def stop(self):
        self._running = False

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    # ── welink-cli ────────────────────────────────────────────────

    def _recent_conversations(self, count: int = 20) -> list:
        data = _run_cli('query-recent-conversation', '--count', str(count))
        return data.get('conversation_info', [])

    def _user_msgs(self, account: str, count: int = 10) -> list:
        data = _run_cli('query-history-message',
                        '--user-account', account, '--query-count', str(count))
        return (data.get('respData') or {}).get('chatInfo', [])

    def _group_msgs(self, group_id: str, count: int = 10) -> list:
        data = _run_cli('query-history-message',
                        '--group-id', group_id, '--query-count', str(count))
        return (data.get('respData') or {}).get('chatInfo', [])

    def _send_user(self, account: str, text: str):
        _run_cli('send-to-user', '--receiver', account, '--text', text)

    def _send_group(self, group_id: str, text: str):
        _run_cli('send-to-group', '--group-id', group_id, '--text', text)

    # ── AI ───────────────────────────────────────────────────────

    def _call_ai(self, message: str) -> str:
        try:
            resp = requests.post(
                f'{self._backend}/api/ai/chat',
                json={'prompt': self._prompt, 'message': message},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get('reply', '')
        except Exception as e:
            self._log(f'AI 调用失败: {e}')
            return ''

    # ── process ───────────────────────────────────────────────────

    def _process(self, sender: str, content: str, history: list,
                 is_group: bool, group_id: str = ''):
        # 最近 6 条聊天记录作上下文（同 welink_usage.txt）
        lines = []
        for m in reversed(history[-6:]):
            c = _norm(m.get('content', ''))
            if c:
                lines.append(f'[{m.get("sender", "")}]: {c}')
        ctx = ('【最近聊天记录】\n' + '\n'.join(lines) + '\n\n') if lines else ''

        tag = '【群聊】' if is_group else '【私聊】'
        message = f'{tag}发送者工号: {sender}\n{ctx}最新消息: {content}'

        reply = self._call_ai(message)
        if not reply:
            return

        short = reply[:60] + ('…' if len(reply) > 60 else '')
        self._log(f'[{"群" if is_group else "私"}][{sender}] → {short}')

        if is_group:
            self._send_group(group_id, reply)
        else:
            self._send_user(sender, reply)

    # ── handlers ─────────────────────────────────────────────────

    def _handle_p2p(self, conv: dict):
        account = conv.get('target_account', '')
        if not account:
            return

        msgs = self._user_msgs(account, 5)
        if not msgs:
            return

        lm  = msgs[0]
        lid = int(lm.get('msgId', 0))

        # 初始化水位线，不回复历史消息
        if self._last_ids.get(account) is None:
            self._last_ids[account] = lid
            return
        if lid == self._last_ids[account]:
            return

        sender = lm.get('sender', '')
        # 只处理对方发来的消息（同 welink_usage.txt）
        if sender != account:
            self._last_ids[account] = lid
            return

        self._last_ids[account] = lid

        content = _norm(lm.get('content', ''))
        if not content or not _is_question(content):
            return

        self._log(f'[私聊][{account}] {content[:60]}')
        self._process(account, content, msgs, is_group=False)

    def _handle_group(self, conv: dict):
        group_id   = str(conv.get('group_id', ''))
        group_name = conv.get('group_name', group_id)
        if not group_id:
            return

        msgs = self._group_msgs(group_id, 5)
        if not msgs:
            return

        lm  = msgs[0]
        lid = int(lm.get('msgId', 0))
        key = f'g:{group_id}'

        if self._last_ids.get(key) is None:
            self._last_ids[key] = lid
            return
        if lid == self._last_ids[key]:
            return

        sender = lm.get('sender', '')
        # 跳过自己发的消息（同 welink_usage.txt）
        if sender == self._bot_id:
            self._last_ids[key] = lid
            return

        # 群聊：仅 @ 我（atAccountList 含机器人工号）才回复
        at_list = lm.get('atAccountList', [])
        if self._bot_id not in at_list:
            self._last_ids[key] = lid
            return

        self._last_ids[key] = lid

        content = _norm(lm.get('content', ''))
        self._log(f'[群聊][{group_name}] {sender}: {content[:60]}')
        self._process(sender, content, msgs, is_group=True, group_id=group_id)

    # ── main loop ─────────────────────────────────────────────────

    def run(self):
        self._running = True
        self._log('自动回复监听已启动')

        while self._running:
            try:
                for conv in self._recent_conversations(20):
                    if not self._running:
                        break
                    ctype = conv.get('recent_conversation_type', '')
                    if ctype == 'CHAT_TYPE_P2P_MSG':
                        self._handle_p2p(conv)
                    elif ctype == 'CHAT_TYPE_GROUP_MSG':
                        self._handle_group(conv)
            except Exception as e:
                self._log(f'轮询出错: {e}')

            time.sleep(self._interval)

        self._log('自动回复监听已停止')
