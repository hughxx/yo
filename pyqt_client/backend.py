"""后端 HTTP 封装"""
import requests

_base = 'http://localhost:8023'

def set_base(url: str):
    global _base
    _base = url.rstrip('/')

def ping() -> bool:
    try:
        return requests.get(f'{_base}/api/email/ping', timeout=5).ok
    except Exception:
        return False

def get_namespaces() -> list:
    try:
        r = requests.get(f'{_base}/api/email/namespaces', timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def get_parse_status(topics: list, namespace: str) -> dict:
    try:
        r = requests.post(f'{_base}/api/email/parse_status',
                          json={'topics': topics, 'namespace': namespace}, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def receive_email(payload: dict) -> dict:
    r = requests.post(f'{_base}/api/email/receive', json=payload, timeout=300)
    r.raise_for_status()
    return r.json()

def get_cloud_rules(namespace: str) -> list:
    try:
        r = requests.get(f'{_base}/api/email/rules', params={'namespace': namespace}, timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def add_cloud_rule(namespace: str, name: str, keywords: list, body_keywords: list, senders: list, logic: str) -> dict:
    r = requests.post(f'{_base}/api/email/rules', json={
        'namespace': namespace, 'name': name,
        'keywords': keywords, 'body_keywords': body_keywords,
        'senders': senders, 'logic': logic,
    }, timeout=10, verify=False)
    r.raise_for_status()
    return r.json()

def edit_cloud_rule(rule_id: int, patch: dict) -> dict:
    r = requests.put(f'{_base}/api/email/rules/{rule_id}', json=patch, timeout=10, verify=False)
    r.raise_for_status()
    return r.json()

def delete_cloud_rule(rule_id: int) -> dict:
    r = requests.delete(f'{_base}/api/email/rules/{rule_id}', timeout=10, verify=False)
    r.raise_for_status()
    return r.json()

def get_userinfo(query: str) -> list:
    try:
        r = requests.get(f'{_base}/api/email/userinfo', params={'info': query}, timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []
