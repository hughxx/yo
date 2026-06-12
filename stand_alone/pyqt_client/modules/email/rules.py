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


def match(email: dict, rules: list, body_matched_map: dict = None) -> str:
    """
    返回第一条匹配规则的名称，无匹配返回空串。

    body_matched_map: {rule_index: set(EntryID)} —— 由 outlook.search_body() 预先填充，
    没有时跳过正文匹配（降级为仅主题/发件人匹配）。
    """
    body_matched_map = body_matched_map or {}
    item_id = email.get('item_id', '')
    subj    = email.get('subject', '').lower()
    s_name  = email.get('sender_name', '').lower()
    s_mail  = email.get('sender_email', '').lower()

    for i, rule in enumerate(rules):
        if not rule.get('enabled', True):
            continue

        kws  = [k.lower() for k in rule.get('keywords', [])]
        bkws = rule.get('body_keywords', [])
        snds = [s.lower() for s in rule.get('senders', [])]
        logic = rule.get('logic', 'OR')

        kw_hit   = bool(kws  and any(k in subj for k in kws))
        body_hit = bool(bkws and item_id in body_matched_map.get(i, set()))
        sn_hit   = bool(snds and any(s in s_name or s in s_mail for s in snds))

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


def build_body_matched_map(rules: list, scan_folders: list) -> dict:
    """
    对所有启用且含 body_keywords 的规则，调用 outlook.search_body() 预查正文。
    返回 {rule_index: set(EntryID)}。
    """
    from modules.email import outlook
    result = {}
    for i, rule in enumerate(rules):
        if not rule.get('enabled', True):
            continue
        bkws = rule.get('body_keywords', [])
        if bkws:
            result[i] = outlook.search_body(scan_folders or None, bkws)
    return result
