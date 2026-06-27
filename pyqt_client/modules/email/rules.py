"""规则本地 JSON 管理"""
import json
import uuid
from pathlib import Path

_FILE = Path.home() / '.email_assistant_rules.json'


def load() -> list:
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text('utf-8'))
        except Exception:
            pass
    return []


def save(rules: list):
    _FILE.write_text(json.dumps(rules, ensure_ascii=False, indent=2), 'utf-8')


def add(name: str, keywords: list, body_keywords: list, senders: list, logic: str = 'OR') -> dict:
    rules = load()
    rule = {
        'id':            str(uuid.uuid4()),
        'name':          name,
        'keywords':      keywords,
        'body_keywords': body_keywords,
        'senders':       senders,
        'logic':         logic,
        'enabled':       True,
    }
    rules.append(rule)
    save(rules)
    return rule


def edit(rule_id: str, patch: dict):
    rules = load()
    for r in rules:
        if r['id'] == rule_id:
            r.update(patch)
            break
    save(rules)


def delete(rule_id: str):
    save([r for r in load() if r['id'] != rule_id])


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
