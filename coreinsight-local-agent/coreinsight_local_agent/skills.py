from __future__ import annotations


WELINK_EXPERIENCE_SKILL_ID = "welink-experience-extractor"
WELINK_EXPERIENCE_SKILL_NAME = "WeLink 经验提取"

WELINK_EXPERIENCE_SKILL = """---
name: welink-experience-extractor
description: 从 WeLink 群聊 Markdown、图片和附件中提取可检索的技术经验。
---

# WeLink 经验提取

## 输入

- 必须读取当前 workspace 下的 `input/chat.md`。
- 聊天中的附件位于 `attachments/`；需要时读取图片、文本、日志或代码附件。
- 图片旁若已有 OCR 文本，结合图片和 OCR 理解，不能把 OCR 噪声当作事实。

## 工作流

1. 按时间顺序完整阅读聊天记录；记录很长时自行分段分析，但最终只能生成一条合并结果。
2. 识别技术问题的背景、现象、分析过程、根因、解决方案和最终结论。
3. 剔除问候、确认、无关闲聊等低价值内容，保留代码、接口、错误日志、配置和关键时间线。
4. 讨论摘要必须使用输入中的真实发送人和时间，不得使用“用户”“发言人”等占位符。
5. 不要在结果中引用 `/workspace` 路径或临时附件链接；用文字总结图片和附件中的有效信息。
6. 将最终结果写入 `output/experience.json`，并在最终回答中原样返回同一个 JSON。

## 输出格式

严格输出 UTF-8 JSON，不要使用 Markdown 代码围栏，不要添加额外说明：

{
  "title": "简洁标题，不超过50字",
  "summary": "背景和结论摘要，不超过200字",
  "experience": "Markdown 正文，按需包含问题背景、问题现象、分析过程、根因、解决方案、讨论摘要",
  "rag_search_text": "空格分隔的检索关键词"
}

四个字段都必须是字符串。无法形成有效技术经验时也要输出合法 JSON，并在 summary 中说明原因。
"""


def available_skills() -> list[dict]:
    return [{
        "id": WELINK_EXPERIENCE_SKILL_ID,
        "name": WELINK_EXPERIENCE_SKILL_NAME,
        "description": "读取聊天记录和附件，提取结构化技术经验并写入经验引擎。",
    }]


def get_skill(skill_id: str) -> dict:
    if skill_id != WELINK_EXPERIENCE_SKILL_ID:
        raise ValueError(f"不支持的 Skill：{skill_id}")
    return {"id": skill_id, "name": WELINK_EXPERIENCE_SKILL_NAME,
            "content": WELINK_EXPERIENCE_SKILL}
