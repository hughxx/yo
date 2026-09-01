from pathlib import Path
import os
import json
import logging
import requests
import base64
import hashlib
import hmac

_CIPHER_KEY = hashlib.sha256(b"coreinsight-local-toolkit-runtime-v1").digest()


def _decrypt(value):
    value = str(value or "")
    if not value.startswith("enc:v1:"):
        return value
    raw = base64.urlsafe_b64decode(value[7:].encode("ascii"))
    nonce, ciphertext, tag = raw[:16], raw[16:-16], raw[-16:]
    expected = hmac.new(_CIPHER_KEY, nonce + ciphertext, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("配置中心密钥校验失败")
    stream = bytearray(); counter = 0
    while len(stream) < len(ciphertext):
        stream.extend(hmac.new(_CIPHER_KEY, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(a ^ b for a, b in zip(ciphertext, stream)).decode("utf-8")


def _config_value(*names, default=""):
    for name in names:
        value = _RUNTIME.get(name)
        if isinstance(value, dict):
            value = value.get("val", value.get("value", ""))
        if value:
            return _decrypt(value)
    return default

ROOT = Path(os.environ.get("COREINSIGHT_MINER_DIR", r"D:\CoreInsight\miner"))
VERSION = "0.1.0"
ROOT.mkdir(parents=True, exist_ok=True)
USER_CONFIG_FILE = ROOT / "miner_config.json"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "miner.log"
WELINK_DIR = ROOT / "聊天记录"
OUTLOOK_DIR = ROOT / "邮件"
WELINK_DIR.mkdir(parents=True, exist_ok=True)
OUTLOOK_DIR.mkdir(parents=True, exist_ok=True)

# These are the same packaged defaults used by the existing client.
def _fetch_runtime_config():
    """Fetch the complete release object from config center.

    The object may contain only UI notices in some deployments, so this
    helper deliberately does not require model credentials to be present.
    """
    url = os.environ.get("COREINSIGHT_RUNTIME_CONFIG_URL", "https://fuyao.rnd.huawei.com/dataengineering/rag-knowledge-config/selectConfigByKey")
    key = os.environ.get("COREINSIGHT_MINER_CONFIG_KEY", "coreinsight_miner_release")
    try:
        response = requests.get(url, params={"key": key}, timeout=10, verify=False)
        response.raise_for_status()
        value = (response.json().get("data") or {}).get("configVal")
        if isinstance(value, str):
            value = json.loads(value)
        return value if isinstance(value, dict) else {}
    except Exception:
        logging.getLogger(__name__).warning("miner runtime config unavailable key=%s", key, exc_info=True)
        return {}


def _runtime_config():
    return _fetch_runtime_config()


def refresh_runtime_config():
    """Refresh the public runtime configuration on demand (for UI notices)."""
    return _fetch_runtime_config()


_RUNTIME = _runtime_config()
APP_NAME = str(_RUNTIME.get("appName") or _RUNTIME.get("app_name") or "邮件聊天记录提取工具")
LATEST_VERSION = str(_RUNTIME.get("latestVersion") or VERSION)
MINIMUM_SUPPORTED_VERSION = str(_RUNTIME.get("minimumSupportedVersion") or VERSION)
FORCE_UPDATE = bool(_RUNTIME.get("forceUpdate", False))
DOWNLOAD_URL = str(_RUNTIME.get("downloadUrl") or "")
RELEASE_NOTES = _RUNTIME.get("releaseNotes") or []
LLM_BASE_URL = os.environ.get("COREINSIGHT_LLM_BASE_URL", _config_value("llm_base_url", "model_gateway_url", default="https://fuyao.rnd.huawei.com/model_gateway/v1"))
LLM_API_KEY = os.environ.get("COREINSIGHT_LLM_API_KEY", _config_value("llm_api_key", "model_gateway_api_key"))
LLM_MODEL_ID = os.environ.get("COREINSIGHT_LLM_MODEL_ID", _config_value("llm_model_id", "model_id", default="a9dc5db2-e625-487c-95a6-69c2be0831ca"))
# WeLink image/file messages need the existing proxy to obtain a readable URL
# and OCR result.  The text/experience result itself is still local-only.
IMAGE_PROXY_URL = os.environ.get("COREINSIGHT_IMAGE_PROXY_URL", "https://coreinsight-beta.rnd.huawei.com/collection")

DEFAULT_PROMPT = """你是经验整理助手。请从下面的 Markdown 中提取可复用的工程经验，输出 Markdown，包含：\n# 标题\n## 背景\n## 问题\n## 方案\n## 结果与注意事项\n只保留有事实依据的内容，不要编造。\n\n原始材料：\n"""
try:
    _user_config = json.loads(USER_CONFIG_FILE.read_text(encoding="utf-8")) if USER_CONFIG_FILE.exists() else {}
except Exception:
    _user_config = {}
PROMPT = str(_user_config.get("prompt") or DEFAULT_PROMPT)
RESOURCE = str(_user_config.get("resource") or "public")


def save_user_config(prompt=None, resource=None):
    global PROMPT, RESOURCE
    if prompt is not None and str(prompt).strip():
        PROMPT = str(prompt)
    if resource in ("public", "local"):
        RESOURCE = resource
    USER_CONFIG_FILE.write_text(json.dumps({"prompt": PROMPT, "resource": RESOURCE}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"prompt": PROMPT, "resource": RESOURCE, "path": str(USER_CONFIG_FILE)}
