from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, validator


class GroupBase(BaseModel):
    groupId: str = Field(min_length=1)
    name: str = ""

    @validator("groupId")
    def normalize_group_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("groupId 不能为空")
        return value

    @validator("name")
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class GroupCreate(GroupBase):
    pass


class GroupConfig(GroupBase):
    status: Literal["idle", "extracting", "scheduled"] = "idle"
    extractMode: Literal["direct", "draft"] = "direct"
    extractMethod: Literal["prompt", "codeagent"] = "prompt"
    startTime: str = ""
    endTime: str = ""
    quickRange: Literal["all", "7d", "3d", "2d", "today", "custom"] = "7d"
    promptContent: str = "从消息中提取关键经验、问题及解决方案，结构化输出为：背景 / 问题 / 方案 / 总结"
    scheduleFreq: Literal["daily", "weekly", "monthly", "custom"] = "daily"
    scheduleTime: str = "09:00:00"
    scheduleCron: str = ""


class GroupDelete(BaseModel):
    groupId: str = Field(min_length=1)


class MessageQuery(BaseModel):
    groupId: str = Field(min_length=1)
    startTime: Optional[str] = None
    endTime: Optional[str] = None


class MessagePageQuery(MessageQuery):
    cursor: str = ""
    limit: int = Field(default=100, ge=1, le=100)


class PreviewMessage(BaseModel):
    id: str
    sender: str
    time: str
    content: str
    checked: bool = True
    contentType: str = "TEXT_MSG"
    timestamp: int = 0


class MessagePage(BaseModel):
    items: list[PreviewMessage]
    nextCursor: str = ""
    hasMore: bool = False
    totalHint: int = 0
