from __future__ import annotations


WELINK_EXPERIENCE_SKILL_ID = "welink-experience-extractor"
WELINK_EXPERIENCE_SKILL_NAME = "WeLink 经验提取"
EMAIL_EXPERIENCE_SKILL_ID = "email-experience-extractor"
EMAIL_EXPERIENCE_SKILL_NAME = "邮件经验提取"

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
6. 先查看已有 `output/experiences.jsonl`。若新聊天补充了某条已有经验，输出 `operation: update`，使用该行的 `doc_id`，合并旧内容与新内容后追加一个完整的新版本；不要创建重复经验。
7. 新主题输出 `operation: create` 且不带 `doc_id`。每形成一条经验，就把一个单行 JSON 追加到 `output/experiences.jsonl`；只能追加，禁止改写或删除旧行。
8. 禁止手工拼接 JSON 字符串。必须使用 Python `json.dumps(record, ensure_ascii=False)` 等标准 JSON 序列化方式写入；结束前必须用 Python `json.loads` 逐行校验整个文件。
9. 没有可沉淀内容时不要输出占位经验，也不要追加任何行。

## 输出格式

JSONL 每行严格为一个 UTF-8 JSON 对象，不要使用 Markdown 代码围栏。字符串中的换行必须由 JSON 转义：

{
  "operation": "create 或 update，必填",
  "doc_id": "已有经验的真实 ID；新经验省略此字段",
  "title": "简洁标题，不超过50字",
  "summary": "详细经验正文，无字数限制",
  "experience": "Markdown 正文，按需包含问题背景、问题现象、分析过程、根因、解决方案、讨论摘要",
  "rag_search_text": "空格分隔的检索关键词"
}

`operation` 必须显式输出。新建时四个业务字段都必须是字符串。更新已有经验时也应输出合并后的完整版本，`doc_id` 必须沿用已有值。
"""


EMAIL_EXPERIENCE_SKILL = """---
name: email-experience-extractor
description: 从 Outlook 邮件 Markdown、附件链接和图片 OCR 中提取可复用技术经验。
---

# 邮件经验提取

## 输入

- 本轮邮件位于 `input/` 下一个或多个 `.md` 文件，必须按六位数字文件名前缀顺序完整读取。
- 每封邮件包含邮件 ID、真实发件人、接收时间、主题、正文和附件。
- 图片统一为 `![OCR结果](公开URL)`；普通附件为 `[文件名](公开URL)`。
- `output/experiences.jsonl` 若存在，是同一长期定时任务此前已入库的经验版本。

## 工作流

1. 从邮件线程中识别值得沉淀的技术问题、背景、现象、分析过程、根因、解决方案、验证结果和关键结论；通知、广告、寒暄及无实质内容的邮件应忽略。
2. 同一会话和同一问题的多封邮件应合并理解，保留真实主题、发件人和接收时间，不得编造结论。
3. 代码、配置、错误日志、命令、接口信息和关键附件必须准确保留。
4. 所有与经验有关的公开图片 Markdown 必须原样保留在最终 `experience` 的对应上下文中，不得删除、改写 URL 或丢弃 OCR alt 文本。
5. 先检查已有 `output/experiences.jsonl`。新邮件补充已有经验时，使用原 `doc_id` 输出 `operation: update`，并输出合并后的完整版本；不得创建重复经验。
6. 新主题输出 `operation: create` 且不带 `doc_id`。每形成一条经验，就向 `output/experiences.jsonl` 追加一个单行 JSON；禁止改写或删除旧行。
7. 禁止手工拼接 JSON 字符串。必须使用 Python `json.dumps(record, ensure_ascii=False)` 等标准 JSON 序列化方式写入；结束前必须用 Python `json.loads` 逐行校验整个文件。
8. 没有可沉淀内容时不追加任何内容。

## 输出格式

每行必须是一个完整 UTF-8 JSON 对象，不使用 Markdown 代码围栏：

{
  "operation": "create 或 update",
  "doc_id": "更新时必填；新建时省略",
  "title": "简洁标题，不超过50字",
  "summary": "完整、详细、可独立阅读的经验正文",
  "experience": "结构化 Markdown 剧本，包含必要的邮件证据和图片",
  "rag_search_text": "空格分隔的检索关键词",
  "scene_id": "251",
  "scene": "邮件技术经验"
}

新建时 title、summary、experience、rag_search_text 必须为非空字符串。更新时必须沿用已有 doc_id，并输出合并后的完整版本。
"""


def available_skills() -> list[dict]:
    return [{
        "id": WELINK_EXPERIENCE_SKILL_ID,
        "name": WELINK_EXPERIENCE_SKILL_NAME,
        "description": "读取聊天记录和附件，提取结构化技术经验并写入经验引擎。",
    }, {
        "id": EMAIL_EXPERIENCE_SKILL_ID,
        "name": EMAIL_EXPERIENCE_SKILL_NAME,
        "description": "读取 Outlook 邮件、附件链接和图片 OCR，提取并合并技术经验。",
    }]


def get_skill(skill_id: str) -> dict:
    skills = {
        WELINK_EXPERIENCE_SKILL_ID: (WELINK_EXPERIENCE_SKILL_NAME,
                                     WELINK_EXPERIENCE_SKILL),
        EMAIL_EXPERIENCE_SKILL_ID: (EMAIL_EXPERIENCE_SKILL_NAME,
                                    EMAIL_EXPERIENCE_SKILL),
    }
    if skill_id not in skills:
        raise ValueError(f"不支持的 Skill：{skill_id}")
    name, content = skills[skill_id]
    return {"id": skill_id, "name": name, "content": content}
