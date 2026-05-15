import asyncio
import json
import logging
import re
import uuid

import requests as req_lib

from server.db.models.welink import WelinkChatlog
from server.db.db import SessionLocal
from server.utils.html2md import html2md
from server.utils.llm import chat, chat_with_tools
from server.utils.img import ocr
from server.utils.engine import push_experience
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
- **讨论摘要**：按时间顺序列出各方关键发言，每条格式为一行：`真实姓名（YYYY-MM-DD HH:MM）：内容`。
  示例：`张三（2026-04-29 16:46）：问题复现了，日志如下…`
  要求：①必须使用聊天记录中的真实发言人姓名，不得写"发言人"、"用户"等占位词；
  ②时间紧跟姓名括号内；③内容与时间在同一行，不换行；
  ④剔除无实质内容的消息（如"好的"、"收到"、"看下"等简短回复）。
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
    group_id:   str = '',
    is_daily:   bool = False,
) -> None:
    if is_daily:
        await _process_daily_chatlog(html_body, group_id, group_name, chat_id, upload_by)
        return

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

        push_experience(result, upload_by, doc_id)
        _update_status(chat_id, "done")
        logger.info("process_chatlog done: group=%r chat_id=%r", group_name, chat_id)
    except Exception:
        logger.exception("process_chatlog failed: group=%r chat_id=%r", group_name, chat_id)
        _update_status(chat_id, "failed")


# ── 按天归档：Agent 定义 ──────────────────────────────────────────

_DAILY_AGENT_SYSTEM = """\
你是一个专业的技术知识整理专家。

下方是今日 WeLink 群聊的过滤记录（已剔除通过手动标记归档过的片段）。
请从头到尾仔细阅读，识别其中的**技术问题定位案例**。

判断标准（同时满足才算一个案例）：
- 有具体的问题现象描述
- 有分析讨论过程
- 有结论或解决方案（即使是暂时结论）

请跳过：纯通知、签到、闲聊、无实质内容的短回复。

**图片处理规则（重要）：**
- 聊天记录中的图片已附加 OCR 识别文字（标注在图片下方），供你理解图片内容
- 在 experience 字段中，图片必须以原始 `![](url)` 超链接格式保留，不得替换为纯文字描述
- OCR 标注文字（`> **[图片文字]** ...`）不要直接复制到 experience，仅用于理解图片含义

每发现一个值得归档的案例，立即调用 create_experience 工具保存。
一份记录可能包含 0 个、1 个或多个案例，按实际情况处理即可。
"""

_CREATE_EXPERIENCE_TOOL = {
    "type": "function",
    "function": {
        "name": "create_experience",
        "description": "保存一条技术问题定位经验",
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
                        "讨论摘要按时间顺序列出关键发言，每条格式为一行：真实姓名（YYYY-MM-DD HH:MM）：内容。"
                        "必须使用聊天记录中的真实发言人姓名，不得写'发言人'等占位词。"
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


async def _run_daily_agent(markdown: str) -> list:
    """Agent loop：读完过滤后的全天记录，对每个发现的案例调用 create_experience。"""
    tools    = [_CREATE_EXPERIENCE_TOOL]
    messages = [
        {"role": "system", "content": _DAILY_AGENT_SYSTEM},
        {"role": "user",   "content": markdown},
    ]
    experiences = []

    for _turn in range(10):  # 防止无限循环
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
                experiences.append(args)
                result = "已保存"
            else:
                result = "unknown tool"

            messages.append({
                "role":         "tool",
                "tool_call_id": tid,
                "content":      result,
            })

    return experiences


def _filter_daily_html(html_body: str, excluded_intervals: list) -> str:
    """从全天 HTML 中剔除已被手动记录覆盖的消息块，返回过滤后的完整 HTML。"""
    import re as _re
    from datetime import datetime

    MSG_OPEN = '<div style="margin:6px 0;padding:6px 10px;background:#f5f5f5;border-radius:4px;">'
    TS_RE = _re.compile(
        r'<span style="font-size:11px;color:#aaa;margin-left:8px">'
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})</span>'
    )

    bs = html_body.find('<body>')
    be = html_body.find('</body>')
    if bs == -1 or be == -1:
        return html_body

    header       = html_body[:bs + len('<body>')]
    footer       = html_body[be:]
    body_content = html_body[bs + len('<body>'):be]

    kept = []
    for part in body_content.split(MSG_OPEN)[1:]:
        div_html = MSG_OPEN + part
        m = TS_RE.search(div_html)
        if m:
            try:
                dt = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                if any(s and e and s <= dt <= e for s, e in excluded_intervals):
                    continue
            except ValueError:
                pass
        kept.append(div_html)

    return (header + ''.join(kept) + footer) if kept else ''


async def _process_daily_chatlog(
    html_body:  str,
    group_id:   str,
    group_name: str,
    chat_id:    str,
    upload_by:  str,
) -> None:
    import re as _re
    from datetime import datetime, timedelta

    date_match = _re.search(r'_(\d{4}-\d{2}-\d{2})_daily$', chat_id)
    if not date_match:
        logger.warning("cannot extract date from daily chat_id=%r", chat_id)
        _update_status(chat_id, "failed")
        return

    date_str  = date_match.group(1)
    day_start = datetime.strptime(date_str, '%Y-%m-%d')
    day_end   = day_start + timedelta(days=1)

    # 查当天手动记录，排除其时间段
    db = SessionLocal()
    try:
        manual_records = db.query(WelinkChatlog).filter(
            WelinkChatlog.group_id == group_id,
            WelinkChatlog.is_daily == 0,
            WelinkChatlog.start_time >= day_start,
            WelinkChatlog.start_time <  day_end,
        ).all()
        excluded = [
            (r.start_time, r.end_time)
            for r in manual_records
            if r.start_time and r.end_time
        ]
    finally:
        db.close()

    logger.info("daily: group=%r date=%s manual_excluded=%d", group_id, date_str, len(excluded))

    filtered_html = _filter_daily_html(html_body, excluded)
    if not filtered_html:
        logger.info("daily: no content after exclusion, group=%r date=%s", group_id, date_str)
        _update_status(chat_id, "done")
        return

    markdown = html2md(filtered_html)
    if not markdown.strip():
        _update_status(chat_id, "done")
        return

    markdown = await asyncio.to_thread(replace_um_images, markdown)
    markdown = await _enrich_with_ocr(markdown)

    logger.info("daily: running agent, group=%r date=%s markdown_len=%d",
                group_id, date_str, len(markdown))
    experiences = await _run_daily_agent(markdown)
    logger.info("daily: agent found %d experience(s), group=%r date=%s",
                len(experiences), group_id, date_str)

    if experiences:
        for i, exp in enumerate(experiences):
            doc_id = _make_doc_id(f'{chat_id}_{i}')
            try:
                push_experience(exp, upload_by, doc_id)
                logger.info("daily exp[%d] pushed: doc_id=%s title=%r",
                            i, doc_id, exp.get("title"))
            except Exception:
                logger.exception("daily exp[%d] push failed: group=%r", i, group_name)

    _update_status(chat_id, "done")
