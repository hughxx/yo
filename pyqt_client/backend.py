"""后端 HTTP 封装"""
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_base = 'http://localhost:8023'

# backendUrl 取此值表示「离线」：不连服务端，只本地导出 html+md。
OFFLINE = 'offline'

def is_offline_url(url: str) -> bool:
    return (url or '').strip().lower() == OFFLINE

def set_base(url: str):
    global _base
    _base = url.rstrip('/')

def ping() -> bool:
    try:
        return requests.get(f'{_base}/api/config/ping', timeout=5, verify=False).ok
    except Exception:
        return False

def get_latest_version() -> dict:
    """返回 {latest, min, url, notes}；失败返回空 dict（静默不打扰用户）。"""
    try:
        r = requests.get(f'{_base}/api/config/version', timeout=8, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

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

# 规则（邮件 + WeLink 监听群）已全部改为本地存储，不再走云端：
#   邮件   → modules/email/rules.py（email_rules.json / email_blacklist.json）
#   WeLink → modules/welink/rules.py
# 服务端 /api/email/rules、/api/welink/rules 端点保留，供旧版本客户端继续使用。
