"""welink-cli 封装：会话列表 + 历史消息（群/个人）+ 翻页拉取。

监听/录制/提取/定时都复用这里，不再各写各的 subprocess。
"""
import json
import subprocess
import sys

_STARTUPINFO = None
if sys.platform == 'win32':
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW


def run(args: list, timeout: int = 30):
    """跑 welink-cli，返回 (parsed_json | None, error | None)。"""
    try:
        r = subprocess.run(
            ['welink-cli'] + args,
            capture_output=True, text=True,
            encoding='utf-8', errors='ignore',
            timeout=timeout, startupinfo=_STARTUPINFO,
        )
        out = (r.stdout or '').strip()
        if not out:
            stderr = (r.stderr or '').strip()[:200] or '(无输出)'
            return None, f'CLI 无输出 (stderr: {stderr})'
        return json.loads(out), None
    except json.JSONDecodeError as e:
        return None, f'JSON 解析失败: {e}'
    except Exception as e:
        return None, str(e)


# ── 会话列表 ──────────────────────────────────────────────
def recent_conversations(count: int = 50):
    """返回 (conversations, error)。每项归一化为：
       {kind: 'group'|'p2p', id, name, account}
       group → id=group_id, name=group_name；p2p → account=target_account, name=native_name。
    """
    d, err = run(['im', 'query-recent-conversation', '--count', str(count)])
    if err:
        return [], err
    out = []
    for c in (d or {}).get('conversation_info', []) or []:
        is_p2p = c.get('recent_conversation_type') == 'CHAT_TYPE_P2P_MSG' or str(c.get('group_id')) == '0'
        if is_p2p:
            out.append({
                'kind': 'p2p',
                'id': '',
                'account': c.get('target_account', ''),
                'name': c.get('native_name') or c.get('staff_name') or c.get('target_account', ''),
            })
        else:
            out.append({
                'kind': 'group',
                'id': str(c.get('group_id', '')),
                'account': '',
                'name': c.get('group_name') or str(c.get('group_id', '')),
            })
    return out, None


# ── 历史消息（单页） ──────────────────────────────────────
def _history_page(conv: dict, count: int, message_id=None):
    """conv = {kind:'group'|'p2p', id, account}。返回 (msgs, err)。"""
    args = ['im', 'query-history-message', '--query-count', str(count)]
    if conv.get('kind') == 'p2p':
        args += ['--user-account', conv.get('account', '')]
    else:
        args += ['--group-id', str(conv.get('id', ''))]
    if message_id is not None:
        args += ['--message-id', str(message_id)]
    d, err = run(args)
    if err:
        return [], err
    if not d:
        return [], 'CLI 无返回'
    if d.get('resultCode') not in ('0', 0):
        return [], f'resultCode={d.get("resultCode")} {d.get("resultContext", "")}'
    return d.get('respData', {}).get('chatInfo', []) or [], None


# ── 翻页拉取一个区间 ──────────────────────────────────────
def fetch_range(conv: dict, since_ms=None, until_ms=None,
                page: int = 100, max_msgs: int = 5000, stop=None):
    """从最新往回翻页累积消息，返回 (msgs_sorted_asc, error)。

    since_ms : 只要 serverSendTime >= since_ms（翻到更早就停）
    until_ms : 只要 serverSendTime <= until_ms（更新的丢弃）
    max_msgs : 安全上限，防止误翻几万条
    stop(msg)-> bool : 命中即停止往回翻（用于“开始关键字”）
    """
    collected = {}
    cursor = None
    pages = 0
    while True:
        if len(collected) >= max_msgs:
            break
        msgs, err = _history_page(conv, page, cursor)
        if err:
            return _finalize(collected, since_ms, until_ms), err
        if not msgs:
            break
        for m in msgs:
            mid = m.get('msgId')
            if mid is not None:
                collected[int(mid)] = m
        # 本批最老一条
        oldest = min(msgs, key=lambda m: int(m.get('msgId', 0)))
        oldest_ts = oldest.get('serverSendTime', 0)
        # 到头了
        if len(msgs) < page:
            break
        # 已翻过 since 边界
        if since_ms is not None and oldest_ts < since_ms:
            break
        # 命中开始关键字
        if stop is not None and any(stop(m) for m in msgs):
            break
        cursor = int(oldest.get('msgId'))
        pages += 1
        if pages > (max_msgs // page) + 2:
            break
    return _finalize(collected, since_ms, until_ms), None


def _finalize(collected: dict, since_ms, until_ms):
    rows = list(collected.values())
    if since_ms is not None:
        rows = [m for m in rows if m.get('serverSendTime', 0) >= since_ms]
    if until_ms is not None:
        rows = [m for m in rows if m.get('serverSendTime', 0) <= until_ms]
    rows.sort(key=lambda m: m.get('serverSendTime', 0))
    return rows
