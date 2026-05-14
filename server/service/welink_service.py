import asyncio
import json
import logging
import re
import uuid

import requests as req_lib

from server.db.models.welink import WelinkChatlog
from server.db.models.email import Collection
from server.db.db import SessionLocal
from server.utils.html2md import html2md
from server.utils.llm import chat
from server.utils.img import ocr
from server.utils.settings import EXPERIENCE_ENGINE_URL
from server.utils.um_content import replace_um_images

logger = logging.getLogger(__name__)

_IMAGE_RE = re.compile(r'(!\[[^\]]*\]\((https?://[^)\s]+)\))')

_SYSTEM_PROMPT = """\
你是一个专业的技术知识整理专家。请将下面的WeLink群聊记录整理成一条结构化经验文档，存入知识库供后续检索和学习。

## 输出要求

严格输出以下 JSON，不要有任何额外说明：

```json
{
  "title": "简洁的经验标题（不超过50字）",
  "summary": "问题背景与最终结论的简短总结（不超过200字）",
  "experience": "详细经验正文（Markdown格式，见下方说明）",
  "rag_search_text": "用于检索的关键词与关键短语，空格分隔，覆盖问题特征、技术术语、接口名称、模块名等"
}
```

## experience 字段写作规则

- 使用 Markdown 格式，结构清晰，包含以下章节（如有内容）：
  `## 问题背景`、`## 问题现象`、`## 分析过程`、`## 根因`、`## 解决方案`、`## 讨论摘要`
- **图片**：在对应章节内使用原始 `![](url)` 语法保留图片，不要省略或替换为文字描述。
  图片下方可添加一行简短说明（来自图片文字标注）。
- **讨论摘要**：按时间顺序列出各方关键发言，格式为 `**发言人（时间）**：内容`，
  剔除无实质内容的消息（如"好的"、"收到"、"看下"等简短回复）。
- 保留代码片段、接口路径、错误日志等技术细节，使用 ` ``` ` 代码块。
- 去掉与问题定位无关的闲聊内容。

## 群聊记录内容

群聊记录中的图片已附加 OCR 识别文字（标注在图片下方），供你理解图片内容，
但在 experience 中请使用 `![](url)` 原始格式，而非 OCR 文字块。
"""


async def _enrich_with_ocr(markdown: str) -> str:
    matches = list(_IMAGE_RE.finditer(markdown))
    if not matches:
        return markdown

    enriched = markdown
    offset = 0
    for m in matches:
        url = m.group(2)
        try:
            resp = req_lib.get(url, timeout=30, verify=False)
            resp.raise_for_status()
            filename = url.rstrip("/").split("/")[-1] or "image.png"
            logger.info("OCR: %s", filename)
            text = await ocr(resp.content, filename)
            if text and text.strip():
                annotation = f"\n> **[图片文字]** {text.strip()}"
                insert_pos = m.end() + offset
                enriched = enriched[:insert_pos] + annotation + enriched[insert_pos:]
                offset += len(annotation)
        except Exception:
            logger.warning("OCR failed for %s", url, exc_info=True)

    return enriched


async def _call_llm(markdown: str) -> dict:
    logger.info("LLM: sending %d chars", len(markdown))
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": markdown},
    ]
    raw = await chat(messages)
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw)
    if fence:
        raw = fence.group(1)
    result = json.loads(raw)
    logger.info("LLM: got title=%r", result.get("title"))
    return result


def _make_doc_id(chat_id: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_DNS, chat_id).hex


def _get_or_create_collection(db, name: str) -> int:
    col = db.query(Collection).filter_by(name=name).first()
    if col is None:
        col = Collection(name=name, description="")
        db.add(col)
        db.flush()
    return col.id


def _push_to_engine(result: dict, user_id: str, scene_id: int, scene: str, doc_id: str) -> None:
    if not EXPERIENCE_ENGINE_URL:
        logger.warning("EXPERIENCE_ENGINE_URL not configured, skipping push")
        return
    body = {
        "doc_id":          doc_id,
        "scene_id":        scene_id,
        "scene":           scene,
        "user_id":         user_id,
        "title":           result.get("title", ""),
        "summary":         result.get("summary", ""),
        "experience":      result.get("experience", ""),
        "rag_search_text": result.get("rag_search_text", ""),
    }
    resp = req_lib.post(EXPERIENCE_ENGINE_URL, json=body, timeout=60, verify=False)
    logger.info(
        "experience engine: doc_id=%s status=%s body=%s",
        doc_id, resp.status_code, resp.text[:200],
    )


def _update_status(chat_id: str, status: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(WelinkChatlog).filter_by(chat_id=chat_id).first()
        if row:
            row.process_status = status
            db.commit()
            logger.info("welink status → %s: chat_id=%r", status, chat_id)
    except Exception:
        db.rollback()
        logger.exception("failed to update welink status")
    finally:
        db.close()


async def process_chatlog(
    html_body:  str,
    group_name: str,
    chat_id:    str,
    upload_by:  str,
) -> None:
    doc_id = _make_doc_id(chat_id)
    logger.info(
        "process_chatlog start: group=%r chat_id=%r user=%r doc_id=%s",
        group_name, chat_id, upload_by, doc_id,
    )
    try:
        markdown = html2md(html_body)
        if not markdown.strip():
            logger.info("process_chatlog: empty markdown, skip")
            return

        logger.info("html2md: %d chars", len(markdown))
        markdown = await asyncio.to_thread(replace_um_images, markdown)
        markdown = await _enrich_with_ocr(markdown)
        result   = await _call_llm(markdown)

        db = SessionLocal()
        try:
            scene_id = _get_or_create_collection(db, group_name)
            db.commit()
        finally:
            db.close()

        _push_to_engine(result, upload_by, scene_id, group_name, doc_id)
        _update_status(chat_id, "done")
        logger.info("process_chatlog done: group=%r chat_id=%r", group_name, chat_id)
    except Exception:
        logger.exception("process_chatlog failed: group=%r chat_id=%r", group_name, chat_id)
        _update_status(chat_id, "failed")
