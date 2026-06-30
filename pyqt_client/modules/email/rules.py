"""规则本地 JSON 管理：白名单(规则) + 黑名单。最终命中 = 规则集合 − 黑名单集合。"""
import json
import uuid
from pathlib import Path

from paths import config_dir, migrate

_FILE  = config_dir() / 'email_rules.json'        # 规则（白名单）
_BLACK = config_dir() / 'email_blacklist.json'    # 黑名单
migrate(Path.home() / '.email_assistant_rules.json', _FILE)


# ── 通用存取（按文件） ─────────────────────────────────────
def _load(f: Path) -> list:
    if f.exists():
        try:
            return json.loads(f.read_text('utf-8'))
        except Exception:
            pass
    return []


def _save(f: Path, rules: list):
    f.write_text(json.dumps(rules, ensure_ascii=False, indent=2), 'utf-8')


def _add(f: Path, name, keywords, body_keywords, senders, logic='OR') -> dict:
    rules = _load(f)
    rule = {
        'id':            str(uuid.uuid4()),
        'name':          name,
        'keywords':      keywords,
        'body_keywords': body_keywords,
        'senders':       senders,
        'logic':         logic,
    }
    rules.append(rule)
    _save(f, rules)
    return rule


def _edit(f: Path, rule_id, patch):
    rules = _load(f)
    for r in rules:
        if r['id'] == rule_id:
            r.update(patch)
            break
    _save(f, rules)


def _delete(f: Path, rule_id):
    _save(f, [r for r in _load(f) if r['id'] != rule_id])


# ── 规则（白名单） ─────────────────────────────────────────
def load() -> list:                return _load(_FILE)
def save(rules: list):             _save(_FILE, rules)
def add(name, kw, bkw, snd, logic='OR'):  return _add(_FILE, name, kw, bkw, snd, logic)
def edit(rule_id, patch):          _edit(_FILE, rule_id, patch)
def delete(rule_id):               _delete(_FILE, rule_id)


# ── 黑名单 ─────────────────────────────────────────────────
def load_blacklist() -> list:      return _load(_BLACK)
def save_blacklist(rules: list):   _save(_BLACK, rules)
def add_blacklist(name, kw, bkw, snd, logic='OR'):  return _add(_BLACK, name, kw, bkw, snd, logic)
def edit_blacklist(rule_id, patch): _edit(_BLACK, rule_id, patch)
def delete_blacklist(rule_id):     _delete(_BLACK, rule_id)


def match(email: dict, rules: list, match_maps: dict = None) -> str:
    """
    返回第一条匹配规则的名称，无匹配返回空串。

    match_maps: 由 build_match_maps() 预填充，结构
        {'subj': {rule_index: set(EntryID)},
         'body': {rule_index: set(EntryID)},
         'sender': {rule_index: set(EntryID)}}
    主题/正文/发件人三类命中均来自 Outlook 自带整词搜索（ci_phrasematch），
    不再在 Python 里做子串包含，避免无关邮件被误命中。
    """
    match_maps = match_maps or {}
    subj_map   = match_maps.get('subj', {})
    body_map   = match_maps.get('body', {})
    sender_map = match_maps.get('sender', {})
    item_id = email.get('item_id', '')

    for i, rule in enumerate(rules):
        if not rule.get('enabled', True):
            continue

        kws   = rule.get('keywords', [])
        bkws  = rule.get('body_keywords', [])
        snds  = rule.get('senders', [])
        logic = rule.get('logic', 'OR')

        kw_hit   = bool(kws  and item_id in subj_map.get(i, ()))
        body_hit = bool(bkws and item_id in body_map.get(i, ()))
        sn_hit   = bool(snds and item_id in sender_map.get(i, ()))

        if logic == 'AND':
            kw_ok   = (not kws)  or kw_hit
            body_ok = (not bkws) or body_hit
            sn_ok   = (not snds) or sn_hit
            if (kws or bkws or snds) and kw_ok and body_ok and sn_ok:
                return rule['name']
        else:
            if kw_hit or body_hit or sn_hit:
                return rule['name']

    return ''


def build_match_maps(rules: list, scan_folders: list) -> dict:
    """
    对每条启用规则，调用 Outlook 整词搜索预查主题/正文/发件人命中。
    返回 {'subj': {i: set}, 'body': {i: set}, 'sender': {i: set}}（按规则下标）。
    """
    from modules.email import outlook
    folders = scan_folders or None
    subj, body, sender = {}, {}, {}
    for i, rule in enumerate(rules):
        if not rule.get('enabled', True):
            continue
        kws  = rule.get('keywords', [])
        bkws = rule.get('body_keywords', [])
        snds = rule.get('senders', [])
        if kws:
            subj[i] = outlook.search_subject(folders, kws)
        if bkws:
            body[i] = outlook.search_body(folders, bkws)
        if snds:
            sender[i] = outlook.search_senders(folders, snds)
    return {'subj': subj, 'body': body, 'sender': sender}
