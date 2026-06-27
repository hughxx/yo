"""后端 HTTP 封装"""
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_base = 'http://localhost:8023'

def set_base(url: str):
    global _base
    _base = url.rstrip('/')

def ping() -> bool:
    try:
        return requests.get(f'{_base}/api/config/ping', timeout=5, verify=False).ok
    except Exception:
        return False

def get_namespaces() -> list:
    try:
        r = requests.get(f'{_base}/api/config/namespaces', timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def get_parse_status(topics: list, namespace: str) -> dict:
    try:
        r = requests.post(f'{_base}/api/email/parse_status',
                          json={'topics': topics, 'namespace': namespace}, timeout=30, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def receive_email(payload: dict) -> dict:
    r = requests.post(f'{_base}/api/email/receive', json=payload, timeout=300, verify=False)
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
        r = requests.get(f'{_base}/api/config/userinfo', params={'info': query}, timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def receive_welink_chatlog(payload: dict) -> dict:
    r = requests.post(f'{_base}/api/welink/receive', json=payload, timeout=60, verify=False)
    r.raise_for_status()
    return r.json()

def upload_image(file_bytes: bytes, filename: str):
    """上传图片到文件服务器，返回公开 URL；失败返回 None。"""
    try:
        r = requests.post(
            f'{_base}/api/image/upload',
            files={'file': (filename, file_bytes)},
            data={'filename': filename},
            timeout=30, verify=False,
        )
        r.raise_for_status()
        data = r.json()
        return data.get('url') if data.get('success') else None
    except Exception:
        return None

# WeLink 监听群规则已改为本地存储（modules/welink/rules.py），不再走云端。
# 服务端 /api/welink/rules 端点保留，供旧版本客户端继续使用。
