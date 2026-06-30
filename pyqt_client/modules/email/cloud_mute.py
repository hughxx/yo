"""云端规则的「本地静音」开关。

云端规则的增删改仍在服务端（共享），但启用/禁用改为本机生效：
被本地静音的云端规则，在本机匹配时视为禁用，不会改动服务端配置、不影响他人。
存于用户主目录的一个 id 列表。
"""
import json
from pathlib import Path

from paths import config_dir, migrate

_FILE = config_dir() / 'email_cloud_muted.json'
migrate(Path.home() / '.email_assistant_cloud_muted.json', _FILE)


def _load_set() -> set:
    if _FILE.exists():
        try:
            return {str(x) for x in json.loads(_FILE.read_text('utf-8'))}
        except Exception:
            pass
    return set()


def _save_set(s: set):
    _FILE.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2), 'utf-8')


def is_muted(rule_id) -> bool:
    return str(rule_id) in _load_set()


def toggle(rule_id) -> bool:
    """翻转某云端规则的本地静音状态，返回翻转后的 muted（True=已本地禁用）。"""
    s = _load_set()
    rid = str(rule_id)
    if rid in s:
        s.discard(rid)
        muted = False
    else:
        s.add(rid)
        muted = True
    _save_set(s)
    return muted


def apply(cloud_rules: list) -> list:
    """套用本地静音：被静音的规则 enabled 置 False（返回副本，不改服务端、不改入参）。"""
    s = _load_set()
    out = []
    for r in cloud_rules:
        rr = dict(r)
        if str(rr.get('id')) in s:
            rr['enabled'] = False
        out.append(rr)
    return out
