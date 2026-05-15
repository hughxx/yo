"""自动回复监听线程：特别关注群/用户 + 最近会话，关键词规则驱动。"""
import json
import re
import subprocess
import sys
import time
import unicodedata

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

_UNICODE_SPACES = re.compile(r'[ -​　\xa0]')


def _norm(text: str) -> str:
    return _UNICODE_SPACES.sub(' ', unicodedata.normalize('NFKC', text))


def _is_trivial(content: str) -> bool:
    c = content.strip().lower()
    for p in NON_QUESTION_PATTERNS:
        if c == p or c.startswith(p + ' ') or c.endswith(' ' + p):
            return True
    return False


def fetch_recent_conversations(count: int = 50) -> list:
    """获取最近会话列表（供面板展示合并用）。"""
    cmd = ['welink-cli', 'im', 'query-recent-conversation', '--count', str(count)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=15, encoding='utf-8', errors='ignore',
                                startupinfo=_STARTUPINFO)
        data = json.loads(result.stdout or '{}')
        return data.get('conversation_info', [])
    except Exception:
        return []


class AutoReplyMonitor(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, groups: list, users: list, rules: list,
                 backend_base: str, poll_interval: int = 5, parent=None):
        """
        groups: [{id, name, at_only}]
        users:  [account_str, ...]
        """
        super().__init__(parent)
        # group_id -> at_only
        self._groups   = {g['id']: {'name': g.get('name', g['id']), 'at_only': g.get('at_only', True)}
                          for g in groups}
        self._users    = set(users)
        self._rules    = rules
        self._backend  = backend_base.rstrip('/')
        self._interval = poll_interval
        self._running  = False
        self._last_ids = {}

    def stop(self):
        self._running = False

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    # ── welink-cli ────────────────────────────────────────────────

    def _run_cli(self, *args) -> dict:
        cmd = ['welink-cli', 'im'] + list(args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=15, encoding='utf-8', errors='ignore',
                                    startupinfo=_STARTUPINFO)
            if result.stderr and result.stderr.strip():
                self._log(f'[CLI stderr] {result.stderr.strip()[:200]}')
            if not result.stdout or not result.stdout.strip():
                self._log(f'[CLI] 无输出: {" ".join(cmd[2:])}')
                return {}
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            self._log(f'[CLI] JSON解析失败: {e}')
            return {}
        except Exception as e:
            self._log(f'[CLI] 执行失败: {e}')
            return {}

    def _recent_conversations(self) -> list:
        data = self._run_cli('query-recent-conversation', '--count', '20')
        return data.get('conversation_info', [])

    def _user_msgs(self, account: str, count: int = 5) -> list:
        data = self._run_cli('query-history-message',
                             '--user-account', account, '--query-count', str(count))
        return (data.get('respData') or {}).get('chatInfo', [])

    def _group_msgs(self, group_id: str, count: int = 5) -> list:
        data = self._run_cli('query-history-message',
                             '--group-id', group_id, '--query-count', str(count))
        return (data.get('respData') or {}).get('chatInfo', [])

    def _send_user(self, account: str, text: str):
        self._run_cli('send-to-user', '--receiver', account, '--text', text)

    def _send_group(self, group_id: str, text: str):
        self._run_cli('send-to-group', '--group-id', group_id, '--text', text)

    # ── rule matching ─────────────────────────────────────────────

    def _match_rule(self, content: str):
        for rule in self._rules:
            for kw in rule.get('keywords', []):
                if kw and kw in content:
                    return rule
        return None

    # ── AI ───────────────────────────────────────────────────────

    def _call_ai(self, prompt: str, message: str) -> str:
        try:
            resp = requests.post(
                f'{self._backend}/api/ai/chat',
                json={'prompt': prompt, 'message': message},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get('reply', '')
        except Exception as e:
            self._log(f'AI 调用失败: {e}')
            return ''

    # ── process ───────────────────────────────────────────────────

    def _process(self, rule: dict, sender: str, content: str, history: list,
                 is_group: bool, group_id: str = ''):
        if rule['action'] == 'fixed':
            reply = rule.get('reply', '')
        else:
            lines = []
            for m in reversed(history[-6:]):
                c = _norm(m.get('content', ''))
                if c:
                    lines.append(f'[{m.get("sender", "")}]: {c}')
            ctx     = ('【最近聊天记录】\n' + '\n'.join(lines) + '\n\n') if lines else ''
            tag     = '【群聊】' if is_group else '【私聊】'
            message = f'{tag}发送者工号: {sender}\n{ctx}最新消息: {content}'
            reply   = self._call_ai(rule.get('prompt', ''), message)

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
        if not account or account not in self._users:
            return

        msgs = self._user_msgs(account, 5)
        if not msgs:
            return

        lm  = msgs[0]
        lid = int(lm.get('msgId', 0))

        if self._last_ids.get(account) is None:
            self._last_ids[account] = lid
            return
        if lid == self._last_ids[account]:
            return
        self._last_ids[account] = lid

        content = _norm(lm.get('content', ''))
        if not content or _is_trivial(content):
            return

        rule = self._match_rule(content)
        if not rule:
            return

        sender = lm.get('sender', account)
        self._log(f'[私聊][{sender}] 命中「{rule["keywords"][0]}」 {content[:40]}')
        self._process(rule, account, content, msgs, is_group=False)

    def _handle_group(self, conv: dict):
        group_id = str(conv.get('group_id', ''))
        if not group_id or group_id not in self._groups:
            return

        grp_cfg    = self._groups[group_id]
        group_name = grp_cfg['name']
        at_only    = grp_cfg['at_only']

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
        self._last_ids[key] = lid

        at_list = lm.get('atAccountList', []) or []
        if at_only and not at_list:
            return

        content = _norm(lm.get('content', ''))
        if not content:
            return

        rule = self._match_rule(content)
        if rule is None:
            return

        sender = lm.get('sender', group_id)
        self._log(f'[群聊][{group_name}] 命中「{rule["keywords"][0]}」 {content[:40]}')
        self._process(rule, sender, content, msgs, is_group=True, group_id=group_id)

    # ── main loop ─────────────────────────────────────────────────

    def run(self):
        self._running = True
        self._log(f'监听启动：{len(self._groups)} 个群组，{len(self._users)} 个用户')

        while self._running:
            try:
                for conv in self._recent_conversations():
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
