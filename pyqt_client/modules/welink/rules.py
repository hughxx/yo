"""聊天记录挖掘来源——本地 JSON 管理。

结构：{id, type: group|user, source_id, source_name, enabled}。
旧的群聊监听规则会在读取时透明迁移为群组来源。
"""
import json
import uuid
from pathlib import Path

from paths import config_dir, migrate

_FILE = config_dir() / 'welink_rules.json'
migrate(Path.home() / '.welink_assistant_rules.json', _FILE)


def load() -> list:
    if _FILE.exists():
        try:
            rows = json.loads(_FILE.read_text('utf-8'))
            normalized = []
            for row in rows:
                source_id = str(row.get('source_id') or row.get('group_id') or '').strip()
                if not source_id:
                    continue
                normalized.append({
                    'id': row.get('id') or str(uuid.uuid4()),
                    'type': 'user' if row.get('type') == 'user' else 'group',
                    'source_id': source_id,
                    'source_name': str(row.get('source_name') or row.get('group_name') or source_id).strip(),
                    'enabled': bool(row.get('enabled', True)),
                })
            return normalized
        except Exception:
            pass
    return []


def save(rules: list):
    _FILE.write_text(json.dumps(rules, ensure_ascii=False, indent=2), 'utf-8')


def add(source_type: str, source_id: str, source_name: str) -> dict:
    """新增聊天来源；同类型、同 ID 不重复添加。"""
    rules = load()
    for r in rules:
        if r.get('type') == source_type and r.get('source_id') == source_id:
            return r
    rule = {
        'id':         str(uuid.uuid4()),
        'type':       'user' if source_type == 'user' else 'group',
        'source_id':  source_id,
        'source_name': source_name,
        'enabled':    True,
    }
    rules.append(rule)
    save(rules)
    return rule


def delete(rule_id) -> None:
    save([r for r in load() if str(r.get('id')) != str(rule_id)])
