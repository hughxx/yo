import logging

import requests

from server.utils.settings import (
    EXPERIENCE_ENGINE_URL,
    EXPERIENCE_SCENE_ID,
    EXPERIENCE_SCENE_NAME,
)

logger = logging.getLogger(__name__)


def push_experience(result: dict, user_id: str, doc_id: str) -> None:
    if not EXPERIENCE_ENGINE_URL:
        logger.warning("EXPERIENCE_ENGINE_URL not configured, skipping push")
        return
    body = {
        "doc_id":          doc_id,
        "scene_id":        EXPERIENCE_SCENE_ID,
        "scene":           EXPERIENCE_SCENE_NAME,
        "user_id":         user_id,
        "title":           result.get("title", ""),
        "summary":         result.get("summary", ""),
        "experience":      result.get("experience", ""),
        "rag_search_text": result.get("rag_search_text", ""),
    }
    resp = requests.post(EXPERIENCE_ENGINE_URL, json=body, timeout=60, verify=False)
    logger.info("engine push: doc_id=%s status=%s resp=%s",
                doc_id, resp.status_code, resp.text[:200])
