from pathlib import Path
import os
import json
import logging
import requests

ROOT = Path(os.environ.get("COREINSIGHT_MINER_DIR", r"D:\CoreInsight\miner"))
ROOT.mkdir(parents=True, exist_ok=True)
WELINK_DIR = ROOT / "聊天记录"
OUTLOOK_DIR = ROOT / "邮件"
WELINK_DIR.mkdir(parents=True, exist_ok=True)
OUTLOOK_DIR.mkdir(parents=True, exist_ok=True)

# These are the same packaged defaults used by the existing client.
def _runtime_config():
    url = os.environ.get("COREINSIGHT_RUNTIME_CONFIG_URL", "https://fuyao.rnd.huawei.com/dataengineering/rag-knowledge-config/selectConfigByKey")
    key = os.environ.get("COREINSIGHT_RUNTIME_CONFIG_KEY", "coreinsight_local_toolkit_release")
    try:
        response = requests.get(url, params={"key": key}, timeout=10, verify=False)
        response.raise_for_status()
        value = (response.json().get("data") or {}).get("configVal")
        if isinstance(value, str):
            value = json.loads(value)
        return value if isinstance(value, dict) else {}
    except Exception:
        logging.getLogger(__name__).warning("miner runtime config unavailable", exc_info=True)
        return {}


_RUNTIME = _runtime_config()
LLM_BASE_URL = os.environ.get("COREINSIGHT_LLM_BASE_URL", _RUNTIME.get("llm_base_url", "https://fuyao.rnd.huawei.com/model_gateway/v1"))
LLM_API_KEY = os.environ.get("COREINSIGHT_LLM_API_KEY", _RUNTIME.get("llm_api_key", ""))
LLM_MODEL_ID = os.environ.get("COREINSIGHT_LLM_MODEL_ID", _RUNTIME.get("llm_model_id", "a9dc5db2-e625-487c-95a6-69c2be0831ca"))
# WeLink image/file messages need the existing proxy to obtain a readable URL
# and OCR result.  The text/experience result itself is still local-only.
IMAGE_PROXY_URL = os.environ.get("COREINSIGHT_IMAGE_PROXY_URL", "https://coreinsight-beta.rnd.huawei.com/collection")

PROMPT = """你是经验整理助手。请从下面的 Markdown 中提取可复用的工程经验，输出 Markdown，包含：\n# 标题\n## 背景\n## 问题\n## 方案\n## 结果与注意事项\n只保留有事实依据的内容，不要编造。\n\n原始材料：\n"""
