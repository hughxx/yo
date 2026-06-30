"""自动回复监听线程：特别关注群/用户 + 最近会话，关键词规则驱动。"""
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime

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

_UNICODE_SPACES = re.compile('[ ​　]')


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
    log_signal  = pyqtSignal(str)
    poll_signal = pyqtSignal(str, str)   # key ('g:{id}' | 'u:{acc}'), 'HH:MM:SS'

    def __init__(self, groups: list, users: list, rules: list,
                 pinned_count: int = 0,
                 backend_base: str = '', poll_interval: int = 5,
                 self_account: str = '', parent=None):
        """
        groups:       [{id, name, at_only}]  — 手动配置的群
        users:        [account_str, ...]     — 手动配置的用户
        pinned_count: 查询最近会话时跳过前 N 个置顶会话
        """
        super().__init__(parent)
        self._groups        = {g['id']: {'name': g.get('name', g['id']), 'at_only': g.get('at_only', True)}
                               for g in groups}
        self._users         = set(users)
        self._rules         = rules
        self._pinned_count  = pinned_count
        self._backend       = backend_base.rstrip('/')
        self._interval      = poll_interval
        self._self_account  = self_account
        self._running       = False
        self._last_ids      = {}
        self._dynamic_groups = {}   # gid -> {name, at_only}  从最近会话动态发现
        self._dynamic_users  = set()

    def stop(self):
        self._running = False

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    # ── welink-cli ────────────────────────────────────────────────

    def _run_cli(self, *args, _retries: int = 3) -> dict:
        cmd = ['welink-cli', 'im'] + list(args)
        for attempt in range(_retries):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=15, encoding='utf-8', errors='ignore',
                                        startupinfo=_STARTUPINFO)
                stderr = (result.stderr or '').strip()
                if stderr:
                    self._log(f'[CLI stderr] {stderr[:200]}')
                    if '429' in stderr:
                        wait = 2 ** attempt + 1   # 2s, 3s, 5s
                        self._log(f'[CLI] 429 限速，{wait}s 后重试（{attempt+1}/{_retries}）')
                        time.sleep(wait)
                        continue
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
        return {}

    def _recent_conversations(self) -> list:
        data = self._run_cli('query-recent-conversation', '--count', '8')
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
        reply = '[自动回复] ' + reply   # 所有自动回复统一前缀，便于对方识别
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

        self.poll_signal.emit(f'u:{account}', datetime.now().strftime('%H:%M:%S'))
        msgs = self._user_msgs(account, 5)
        if not msgs:
            self._log(f'[私聊][{account}] 无消息')
            return

        lm  = msgs[0]
        lid = int(lm.get('msgId', 0))

        if self._last_ids.get(account) is None:
            self._log(f'[私聊][{account}] 首次记录 msgId={lid}')
            self._last_ids[account] = lid
            return
        if lid == self._last_ids[account]:
            return
        self._last_ids[account] = lid

        if lm.get('sender') != account:
            self._log(f'[私聊][{account}] 跳过（自己发的消息）')
            return

        content = _norm(lm.get('content', '')).strip()
        self._log(f'[私聊][{account}] 新消息: {content[:60]}')
        if not content:
            self._log(f'[私聊][{account}] 内容为空，消息字段: {list(lm.keys())} raw={repr(lm.get("content",""))[:80]}')
            return
        if _is_trivial(content):
            self._log(f'[私聊][{account}] 跳过（无效内容）')
            return

        rule = self._match_rule(content)
        if not rule:
            self._log(f'[私聊][{account}] 无匹配规则')
            return

        sender = lm.get('sender', account)
        self._log(f'[私聊][{sender}] 命中「{rule["keywords"][0]}」 {content[:40]}')
        self._process(rule, account, content, msgs, is_group=False)

    def _handle_group(self, conv: dict):
        group_id = str(conv.get('group_id', ''))
        if not group_id:
            return

        self.poll_signal.emit(f'g:{group_id}', datetime.now().strftime('%H:%M:%S'))
        grp_cfg    = self._groups.get(group_id, {})
        group_name = grp_cfg.get('name', conv.get('group_name', group_id))
        at_only    = grp_cfg.get('at_only', True)  # 未配置群默认仅@我

        msgs = self._group_msgs(group_id, 5)
        if not msgs:
            self._log(f'[群聊][{group_name}] 无消息')
            return

        lm  = msgs[0]
        lid = int(lm.get('msgId', 0))
        key = f'g:{group_id}'

        if self._last_ids.get(key) is None:
            self._log(f'[群聊][{group_name}] 首次记录 msgId={lid}')
            self._last_ids[key] = lid
            return
        if lid == self._last_ids[key]:
            return
        self._last_ids[key] = lid

        sender = lm.get('sender', '')
        if self._self_account and sender == self._self_account:
            self._log(f'[群聊][{group_name}] 跳过（自己发的消息）')
            return

        at_list = lm.get('atAccountList', []) or []
        content = _norm(lm.get('content', '')).strip()
        self._log(f'[群聊][{group_name}] 新消息: sender={sender} at={at_list} content={content[:60]}')

        if at_only and not at_list:
            self._log(f'[群聊][{group_name}] 跳过（仅@我 但未被@）')
            return

        if not content:
            self._log(f'[群聊][{group_name}] 内容为空，消息字段: {list(lm.keys())} raw={repr(lm.get("content",""))[:80]}')
            return

        rule = self._match_rule(content)
        if rule is None:
            self._log(f'[群聊][{group_name}] 无匹配规则，关键词={[r["keywords"] for r in self._rules]}')
            return

        sender = lm.get('sender', group_id)
        self._log(f'[群聊][{group_name}] 命中「{rule["keywords"][0]}」 {content[:40]}')
        self._process(rule, sender, content, msgs, is_group=True, group_id=group_id)

    # ── main loop ─────────────────────────────────────────────────

    def _refresh_dynamic(self):
        """从最近会话中动态发现需要监听的群/用户（跳过置顶部分）。"""
        count = self._pinned_count + 10
        data  = self._run_cli('query-recent-conversation', '--count', str(count))
        convs = data.get('conversation_info', [])

        new_grps = {}
        new_usrs = set()
        skipped  = 0
        for conv in convs:
            ctype = conv.get('recent_conversation_type', '')
            if ctype not in ('CHAT_TYPE_GROUP_MSG', 'CHAT_TYPE_P2P_MSG'):
                continue
            if skipped < self._pinned_count:
                skipped += 1
                continue
            if ctype == 'CHAT_TYPE_GROUP_MSG':
                gid = str(conv.get('group_id', ''))
                if gid and gid not in self._groups:
                    new_grps[gid] = {'name': conv.get('group_name', gid), 'at_only': True}
            else:
                acc = conv.get('target_account', '')
                if acc and acc not in self._users:
                    new_usrs.add(acc)

        added_g = set(new_grps) - set(self._dynamic_groups)
        added_u = new_usrs - self._dynamic_users
        self._dynamic_groups = new_grps
        self._dynamic_users  = new_usrs
        if added_g or added_u:
            self._log(f'[最近会话] 新增 {len(added_g)} 群 / {len(added_u)} 用户')

    def _poll_once(self):
        all_groups = {**self._groups, **self._dynamic_groups}
        for gid, cfg in all_groups.items():
            if not self._running:
                return
            self._handle_group({'group_id': gid, 'group_name': cfg['name']})
            time.sleep(1.0)

        all_users = self._users | self._dynamic_users
        for acc in all_users:
            if not self._running:
                return
            self._handle_p2p({'target_account': acc})
            time.sleep(1.0)

    def run(self):
        self._running = True
        self._log(f'监听启动：{len(self._groups)} 个配置群组，{len(self._users)} 个配置用户')

        refresh_every = max(1, 60 // max(1, self._interval))  # 约每 60s 刷新一次最近会话
        cycle = 0

        while self._running:
            try:
                if cycle % refresh_every == 0:
                    self._refresh_dynamic()
                cycle += 1
                self._poll_once()
            except Exception as e:
                self._log(f'轮询出错: {e}')
            time.sleep(self._interval)

        self._log('自动回复监听已停止')
