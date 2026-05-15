import asyncio
import json
import logging
import re
import uuid

import requests as req_lib

from server.db.models.email import Email, EmailNamespace
from server.db.db import SessionLocal
from server.utils.html2md import html2md
from server.utils.llm import chat_with_tools
from server.utils.img import ocr
from server.utils.engine import push_experience
from server.utils.um_content import replace_um_images

logger = logging.getLogger(__name__)

_IMAGE_RE = re.compile(r'(!\[[^\]]*\]\((https?://[^)\s]+)\))')

_SYSTEM_PROMPT = """\
你是一个专业的技术知识整理专家。请将下面的邮件线程整理成一条结构化经验文档，存入知识库供后续检索和学习。

## experience 字段写作规则

- 使用 Markdown 格式，结构清晰，包含以下章节（如有内容）：
  `## 问题背景`、`## 问题现象`、`## 分析过程`、`## 根因`、`## 解决方案`、`## 讨论摘要`
- **图片**：在对应章节内使用原始 `![](url)` 语法保留图片，不要省略或替换为文字描述。
  图片下方可添加一行简短说明（来自图片文字标注）。
- **讨论摘要**：按时间顺序列出各方关键回复，每条格式为一行：`真实姓名（YYYY-MM-DD HH:MM）：内容`。
  示例：`张三（2026-04-29 16:46）：问题复现了，日志如下…`
  要求：①必须使用邮件中的真实发件人姓名，不得写"发件人"、"用户"等占位词；
  ②时间紧跟姓名括号内；③内容与时间在同一行，不换行；
  ④剔除无实质内容的转发（如"麻烦看下"、"已对齐"等）。
- 去掉收件人/抄送列表等邮件头部噪声，只保留发件人和发送时间。
- 保留代码片段、接口路径、错误日志等技术细节，使用 ``` 代码块。

## 邮件内容

邮件中的图片已附加 OCR 识别文字（标注在图片下方），供你理解图片内容，
但在 experience 中请使用 `![](url)` 原始格式，而非 OCR 文字块。

仔细阅读邮件内容后，调用 create_experience 工具保存整理好的经验。
"""

_CREATE_EXPERIENCE_TOOL = {
    "type": "function",
    "function": {
        "name": "create_experience",
        "description": "保存一条从邮件线程整理出的技术问题定位经验",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "简洁的经验标题，不超过 50 字",
                },
                "summary": {
                    "type": "string",
                    "description": "问题背景与最终结论的简短总结，不超过 200 字",
                },
                "experience": {
                    "type": "string",
                    "description": (
                        "详细经验正文（Markdown 格式）。"
                        "包含章节：## 问题背景、## 问题现象、## 分析过程、## 根因、"
                        "## 解决方案、## 讨论摘要。"
                        "保留图片 ![](url)、代码块、接口路径、错误日志等技术细节。"
                        "讨论摘要按时间顺序列出关键回复，每条格式为一行：真实姓名（YYYY-MM-DD HH:MM）：内容。"
                        "必须使用邮件中的真实发件人姓名，不得写'发件人'等占位词。"
                        "示例：张三（2026-04-29 16:46）：问题复现了，日志如下…"
                    ),
                },
                "rag_search_text": {
                    "type": "string",
                    "description": "检索用关键词，空格分隔，覆盖技术术语、接口名、模块名等",
                },
            },
            "required": ["title", "summary", "experience", "rag_search_text"],
        },
    },
}


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


async def _run_agent(markdown: str) -> dict | None:
    logger.info("LLM agent: sending %d chars", len(markdown))
    tools    = [_CREATE_EXPERIENCE_TOOL]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": markdown},
    ]
    result = None

    for _turn in range(5):
        assistant_msg = await chat_with_tools(messages, tools)
        tool_calls    = assistant_msg.get("tool_calls") or []

        if not tool_calls:
            break

        messages.append(assistant_msg)

        for tc in tool_calls:
            fn   = tc.get("function", {})
            name = fn.get("name", "")
            tid  = tc.get("id", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except Exception:
                args = {}

            if name == "create_experience":
                if result is None:
                    result = args
                    logger.info("LLM agent: got title=%r", args.get("title"))
                tool_result = "已保存"
            else:
                tool_result = "unknown tool"

            messages.append({
                "role":         "tool",
                "tool_call_id": tid,
                "content":      tool_result,
            })

    return result


def _make_doc_id(conversation_topic: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_DNS, conversation_topic).hex


def _update_ns_status(conversation_topic: str, namespace_id: int, status: str) -> None:
    if not namespace_id:
        return
    db = SessionLocal()
    try:
        email = db.query(Email).filter_by(conversation_topic=conversation_topic).first()
        if email:
            ns = db.query(EmailNamespace).filter_by(
                email_id=email.id, namespace_id=namespace_id
            ).first()
            if ns:
                ns.status = status
                db.commit()
                logger.info(
                    "ns status → %s: topic=%r ns_id=%s",
                    status, conversation_topic[:40], namespace_id,
                )
    except Exception:
        db.rollback()
        logger.exception("failed to update ns status")
    finally:
        db.close()


async def process_email(
    html_body:          str,
    subject:            str,
    user_id:            str,
    namespace_id:       int,
    namespace_name:     str,
    conversation_topic: str,
) -> None:
    doc_id = _make_doc_id(conversation_topic)
    logger.info(
        "process_email start: subject=%r user=%r ns_id=%s ns=%r doc_id=%s",
        subject, user_id, namespace_id, namespace_name, doc_id,
    )
    try:
        markdown = html2md(html_body)
        if not markdown.strip():
            logger.info("process_email: empty markdown, skip")
            return

        logger.info("html2md: %d chars", len(markdown))
        markdown = await asyncio.to_thread(replace_um_images, markdown)
        markdown = await _enrich_with_ocr(markdown)
        result   = await _run_agent(markdown)
        if result is None:
            logger.warning("process_email: agent returned no experience, subject=%r", subject)
            _update_ns_status(conversation_topic, namespace_id, "failed")
            return

        push_experience(result, user_id, doc_id)
        _update_ns_status(conversation_topic, namespace_id, "done")
        logger.info("process_email done: subject=%r", subject)
    except Exception:
        logger.exception("process_email failed: subject=%r", subject)
        _update_ns_status(conversation_topic, namespace_id, "failed")
