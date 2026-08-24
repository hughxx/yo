"""Runtime credentials loaded from the CoreInsight configuration center.

The module name is kept for import compatibility with older builds. Runtime
credentials are no longer encrypted in the executable; the configuration
center is the source of truth.
"""
from __future__ import annotations

import json
import logging
import os

import requests


CONFIG_URL = os.environ.get(
    "COREINSIGHT_RUNTIME_CONFIG_URL",
    "https://fuyao.rnd.huawei.com/dataengineering/rag-knowledge-config/selectConfigByKey",
).strip()
CONFIG_KEY = os.environ.get(
    "COREINSIGHT_RUNTIME_CONFIG_KEY",
    "coreinsight_local_toolkit_runtime",
).strip()


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

        def value(*names: str) -> str:
            for name in names:
                item = raw.get(name)
                if item is not None and str(item).strip():
                    return str(item).strip()
            return ""

        return {
            "clouddrive_account": value("clouddrive_account", "clouddriveAccount"),
            "clouddrive_password": value("clouddrive_password", "clouddrivePassword"),
            "hermes_api_key": value("hermes_api_key", "hermesApiKey"),
        }
    except Exception:
        logging.getLogger(__name__).warning(
            "runtime config center unavailable key=%s", CONFIG_KEY,
            exc_info=True)
        return {}
