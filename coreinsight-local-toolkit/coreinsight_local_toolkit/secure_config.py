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
# Compatibility with builds that used this key before the unified config.
LEGACY_CONFIG_KEY = "coreinsight_local_toolkit_runtime"
MODEL_CONFIG_KEY = os.environ.get(
    "COREINSIGHT_MODEL_CONFIG_KEY", "coreinsight_miner_release"
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
    merged: dict[str, str] = {}
    for config_key in dict.fromkeys(
            (CONFIG_KEY, LEGACY_CONFIG_KEY, MODEL_CONFIG_KEY)):
      if not config_key:
        continue
      try:
        response = requests.get(
            CONFIG_URL, params={"key": config_key},
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
                if isinstance(item, dict):
                    encrypted = bool(item.get("encrypted", False))
                    item = item.get("val", item.get("value", ""))
                    if encrypted or str(item).startswith("enc:v1:"):
                        return decrypt_secret(str(item))
                if item is not None and str(item).strip():
                    text = str(item).strip()
                    # Accept the compact legacy form: "enc:v1:...".
                    return decrypt_secret(text) if text.startswith("enc:v1:") else text
            return ""

        result = {
            "experience_engine_url": value(public, "experience_engine_url", "experienceEngineUrl"),
            "draft_api_url": value(public, "draft_api_url", "draftApiUrl"),
            "ocr_url": value(public, "ocr_url", "ocrUrl"),
            "image_file_server_url": value(public, "image_file_server_url", "imageFileServerUrl"),
            "rag_pic_public_base": value(public, "rag_pic_public_base", "ragPicPublicBase"),
            "notification_url": value(public, "notification_url", "notificationUrl"),
            "clouddrive_account": value(secrets, "clouddrive_account", "clouddriveAccount"),
            "clouddrive_password": value(secrets, "clouddrive_password", "clouddrivePassword"),
            "llm_base_url": value(public, "llm_base_url", "model_gateway_url", "llmBaseUrl"),
            "llm_model_id": value(public, "llm_model_id", "model_id", "llmModelId"),
            "codeagent_model": value(public, "codeagent_model", "codeagentModel"),
            "llm_api_key": value(secrets, "llm_api_key", "model_gateway_api_key", "llmApiKey"),
        }
        for name, item in result.items():
            if item and not merged.get(name):
                merged[name] = item
        if merged.get("llm_api_key"):
            logging.getLogger(__name__).info(
                "runtime model config loaded key=%s llm_key_present=%s llm_key_len=%d llm_key_sha256=%s",
                config_key, True, len(merged["llm_api_key"]),
                hashlib.sha256(merged["llm_api_key"].encode()).hexdigest()[:12],
            )
            return merged
      except Exception:
        logging.getLogger(__name__).warning(
            "runtime config center unavailable key=%s", config_key,
            exc_info=True)
    return merged
