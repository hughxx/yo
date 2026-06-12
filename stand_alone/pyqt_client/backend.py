"""Offline/local backend facade used by the PyQt client."""
import hashlib
import json
import uuid

import requests
import urllib3

import local_archive
import store
from modules.email import rules as email_rules

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_base = 'http://localhost:8023'


def set_base(url: str):
    global _base
    _base = (url or '').rstrip('/')


def ping() -> bool:
    return True


def get_namespaces() -> list:
    ns = store.load_settings().get('namespace') or 'local'
    return [{'name': ns}]


def get_parse_status(topics: list, namespace: str) -> dict:
    return local_archive.parse_status(topics)


def receive_email(payload: dict) -> dict:
    return local_archive.save_email(payload)


def get_cloud_rules(namespace: str) -> list:
    return []


def add_cloud_rule(namespace: str, name: str, keywords: list,
                   body_keywords: list, senders: list, logic: str) -> dict:
    return email_rules.add(name, keywords, body_keywords, senders, logic)


def edit_cloud_rule(rule_id, patch: dict) -> dict:
    email_rules.edit(str(rule_id), patch)
    for rule in email_rules.load():
        if str(rule.get('id')) == str(rule_id):
            return rule
    return {'success': True}


def delete_cloud_rule(rule_id) -> dict:
    email_rules.delete(str(rule_id))
    return {'success': True}


def get_userinfo(query: str) -> list:
    return []


def receive_welink_chatlog(payload: dict) -> dict:
    return local_archive.save_welink(payload)


def upload_image(file_bytes: bytes, filename: str):
    """Upload an image directly from the client and return a public URL.

    Configure store keys:
    - fileServerUrl: upload base, e.g. http://host:port
    - imagePublicBase: public base, e.g. https://public-host
    """
    settings = store.load_settings()
    file_server = (settings.get('fileServerUrl') or '').rstrip('/')
    public_base = (settings.get('imagePublicBase') or '').rstrip('/')
    if not file_server:
        return None

    try:
        digest = hashlib.sha256(file_bytes).hexdigest()
        cache = _load_image_cache()
        if digest in cache:
            return cache[digest]

        object_id = str(uuid.uuid4())
        resp = requests.post(
            f'{file_server}/rag_pic/{object_id}',
            files={'file': (filename, file_bytes)},
            timeout=30,
            verify=False,
        )
        resp.raise_for_status()

        url = local_archive.public_url_from_upload(
            file_server, public_base, object_id, filename,
        )
        cache[digest] = url
        _save_image_cache(cache)
        return url
    except Exception:
        return None


def get_welink_rules() -> list:
    return _load_welink_rules()


def add_welink_rule(group_id: str, group_name: str) -> dict:
    rules = _load_welink_rules()
    if any(str(r.get('group_id')) == str(group_id) for r in rules):
        return {'message': 'rule already exists'}
    rule = {
        'id': str(uuid.uuid4()),
        'group_id': group_id,
        'group_name': group_name,
        'enabled': True,
    }
    rules.append(rule)
    _save_welink_rules(rules)
    return rule


def delete_welink_rule(rule_id) -> dict:
    _save_welink_rules([
        r for r in _load_welink_rules()
        if str(r.get('id')) != str(rule_id)
    ])
    return {'success': True}


def update_welink_rule_name(rule_id, group_name: str) -> dict:
    return _patch_welink_rule(rule_id, {'group_name': group_name})


def toggle_welink_rule(rule_id, enabled: bool) -> dict:
    return _patch_welink_rule(rule_id, {'enabled': enabled})


def _json_file(name: str):
    return store._app_dir() / name


def _load_json(name: str, default):
    try:
        return json.loads(_json_file(name).read_text('utf-8'))
    except Exception:
        return default


def _save_json(name: str, data):
    _json_file(name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        'utf-8',
    )


def _load_welink_rules() -> list:
    return _load_json('.welink_rules.json', [])


def _save_welink_rules(rules: list):
    _save_json('.welink_rules.json', rules)


def _patch_welink_rule(rule_id, patch: dict) -> dict:
    rules = _load_welink_rules()
    result = {'success': False}
    for rule in rules:
        if str(rule.get('id')) == str(rule_id):
            rule.update(patch)
            result = rule
            break
    _save_welink_rules(rules)
    return result


def _load_image_cache() -> dict:
    return _load_json('.image_upload_cache.json', {})


def _save_image_cache(cache: dict):
    _save_json('.image_upload_cache.json', cache)
