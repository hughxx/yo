"""Runtime credentials loaded from the CoreInsight configuration center.

The module name is kept for import compatibility with older builds. Runtime
credentials are no longer encrypted in the executable; the configuration
center is the source of truth.
"""
from __future__ import annotations

import json
import base64
import hashlib
import hmac
import logging
import os

import requests


CONFIG_URL = os.environ.get(
    "COREINSIGHT_RUNTIME_CONFIG_URL",
    "https://fuyao.rnd.huawei.com/dataengineering/rag-knowledge-config/selectConfigByKey",
).strip()
CONFIG_KEY = os.environ.get(
    "COREINSIGHT_RUNTIME_CONFIG_KEY",
    "coreinsight_local_toolkit_release",
).strip()
_CIPHER_KEY = hashlib.sha256(
    b"coreinsight-local-toolkit-runtime-v1"
).digest()


def decrypt_secret(value: str) -> str:
    """Decrypt an enc:v1 value from config center.

    Plain values remain accepted during migration, but new configuration
    should use the enc:v1 form for passwords and API keys.
    """
    value = str(value or "")
    if not value.startswith("enc:v1:"):
        return value
    raw = base64.urlsafe_b64decode(value[7:].encode("ascii"))
    nonce, ciphertext, tag = raw[:16], raw[16:-16], raw[-16:]
    expected = hmac.new(_CIPHER_KEY, nonce + ciphertext, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("运行配置密文校验失败")
    stream = bytearray()
    counter = 0
    while len(stream) < len(ciphertext):
        stream.extend(hmac.new(
            _CIPHER_KEY, nonce + counter.to_bytes(4, "big"), hashlib.sha256
        ).digest())
        counter += 1
    return bytes(a ^ b for a, b in zip(ciphertext, stream)).decode("utf-8")


def packaged_config() -> dict[str, str]:
    """Read runtime credentials from config center.

    Config-center failures are intentionally non-fatal at startup. The
    extraction validation will report the missing specific credential when a
    feature actually needs it.
    """
    if not CONFIG_URL or not CONFIG_KEY:
        return {}
    try:
        response = requests.get(
            CONFIG_URL, params={"key": CONFIG_KEY},
            timeout=10, verify=False)
        response.raise_for_status()
        body = response.json()
        raw = (body.get("data") or {}).get("configVal") if isinstance(body, dict) else None
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ValueError("configVal 不是 JSON 对象")

        public = raw.get("public") if isinstance(raw.get("public"), dict) else raw
        secrets = raw.get("secrets") if isinstance(raw.get("secrets"), dict) else raw

        def value(source: dict, *names: str) -> str:
            for name in names:
                item = source.get(name)
                if item is not None and str(item).strip():
                    return str(item).strip()
            return ""

        return {
            "hermes_url": value(public, "hermes_url", "hermesUrl"),
            "workspace_file_server_url": value(public, "workspace_file_server_url", "workspaceFileServerUrl"),
            "experience_engine_url": value(public, "experience_engine_url", "experienceEngineUrl"),
            "draft_api_url": value(public, "draft_api_url", "draftApiUrl"),
            "ocr_url": value(public, "ocr_url", "ocrUrl"),
            "image_file_server_url": value(public, "image_file_server_url", "imageFileServerUrl"),
            "rag_pic_public_base": value(public, "rag_pic_public_base", "ragPicPublicBase"),
            "notification_url": value(public, "notification_url", "notificationUrl"),
            "clouddrive_account": value(secrets, "clouddrive_account", "clouddriveAccount"),
            "clouddrive_password": decrypt_secret(value(secrets, "clouddrive_password", "clouddrivePassword")),
            "hermes_api_key": decrypt_secret(value(secrets, "hermes_api_key", "hermesApiKey")),
        }
    except Exception:
        logging.getLogger(__name__).warning(
            "runtime config center unavailable key=%s", CONFIG_KEY,
            exc_info=True)
        return {}
