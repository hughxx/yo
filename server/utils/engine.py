import logging

import requests

from server.utils.settings import EXPERIENCE_ENGINE_URL

logger = logging.getLogger(__name__)


def push_experience(result: dict, user_id: str, doc_id: str) -> None:
    body = {
        "doc_id":          doc_id,
        "scene_id":        "251",
        "scene":           "邮件问题定位经验",
        "user_id":         user_id,
        "title":           result.get("title", ""),
        "summary":         result.get("summary", ""),
        "experience":      result.get("experience", ""),
        "rag_search_text": result.get("rag_search_text", ""),
    }
    resp = requests.post(EXPERIENCE_ENGINE_URL, json=body, timeout=60, verify=False)
    logger.info("engine push: doc_id=%s status=%s resp=%s",
                doc_id, resp.status_code, resp.text[:200])
