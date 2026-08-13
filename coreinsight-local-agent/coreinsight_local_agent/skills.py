from __future__ import annotations


WELINK_EXPERIENCE_SKILL_ID = "welink-experience-extractor"
WELINK_EXPERIENCE_SKILL_NAME = "WeLink 经验提取"

WELINK_EXPERIENCE_SKILL = """---
name: welink-experience-extractor
description: 从带公开图片链接和 OCR alt 文本的 WeLink 群聊 Markdown 中提取可检索的技术经验。
---

# WeLink 经验提取

## 输入

- 本轮新增聊天记录位于 `input/` 下一个或多个 `.md` 文件中；必须按六位数字开头的文件名顺序读取。
- 每个文件都只在完整消息边界切分，同一条消息不会被拆到两个文件。
- 图片已经转换为公开可访问的 Markdown `![OCR结果](url)`。
- 必须结合图片和 OCR 理解，不能把 OCR 噪声当作事实。
- `output/experiences.jsonl`（如果存在）是此前已经处理过的经验版本；每一行是一个完整 JSON 对象。

## 工作流

1. 按文件名和消息时间顺序完整阅读本轮聊天记录；可以生成零条、一条或多条独立经验。
2. 识别技术问题的背景、现象、分析过程、根因、解决方案和最终结论。
3. 剔除问候、确认、无关闲聊等低价值内容，保留代码、接口、错误日志、配置和关键时间线。
4. 讨论摘要必须使用输入中的真实发送人和时间，不得使用“用户”“发言人”等占位符。
5. 输入中的所有公开图片 `![OCR结果](url)` 必须原样保留在最终 experience 的对应上下文中，不得删除、改写 URL、清空 alt 文本或只保留 OCR 文字。
6. 先查看已有 `output/experiences.jsonl`。若新聊天补充了某条已有经验，使用该行的 `doc_id`，合并旧内容与新内容后追加一个完整的新版本；不要创建重复经验。
7. 新主题不带 `doc_id`。每形成一条经验，就把一个单行 JSON 追加到 `output/experiences.jsonl`；只能追加，禁止改写或删除旧行。
8. 没有可沉淀内容时不要输出占位经验，也不要追加任何行。

## 输出格式

JSONL 每行严格为一个 UTF-8 JSON 对象，不要使用 Markdown 代码围栏。字符串中的换行必须由 JSON 转义：

{
  "doc_id": "已有经验的真实 ID；新经验省略此字段",
  "title": "简洁标题，不超过50字",
  "summary": "详细经验正文，无字数限制",
  "experience": "Markdown 正文，按需包含问题背景、问题现象、分析过程、根因、解决方案、讨论摘要",
  "rag_search_text": "空格分隔的检索关键词"
}

新建时四个业务字段都必须是字符串。更新已有经验时也应输出合并后的完整版本，`doc_id` 必须沿用已有值。
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
