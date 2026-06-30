"""WeLink 监听群规则——本地 JSON 管理（不再走云端）。

规则结构：{id, group_id, group_name, enabled}，与旧云端规则字段保持一致，
便于 panel/monitor 复用。存于用户主目录，单机持久。
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
            return json.loads(_FILE.read_text('utf-8'))
        except Exception:
            pass
    return []


def save(rules: list):
    _FILE.write_text(json.dumps(rules, ensure_ascii=False, indent=2), 'utf-8')


def add(group_id: str, group_name: str) -> dict:
    """新增一条监听群规则；同 group_id 已存在则直接返回原规则，不重复添加。"""
    rules = load()
    for r in rules:
        if r.get('group_id') == group_id:
            return r
    rule = {
        'id':         str(uuid.uuid4()),
        'group_id':   group_id,
        'group_name': group_name,
        'enabled':    True,
    }
    rules.append(rule)
    save(rules)
    return rule


def delete(rule_id) -> None:
    save([r for r in load() if str(r.get('id')) != str(rule_id)])
