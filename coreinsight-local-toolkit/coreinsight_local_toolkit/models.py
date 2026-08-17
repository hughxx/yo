from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, validator

from .time_format import normalize_datetime


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
    skillId: str = "welink-experience-extractor"
    uploadBy: str = ""
    startTime: str = ""
    endTime: str = ""
    quickRange: Literal["all", "7d", "3d", "2d", "today", "custom"] = "7d"
    scheduleFreq: Literal["daily", "weekly", "monthly", "custom"] = "daily"
    scheduleTime: str = "09:00:00"
    scheduleCron: str = ""
    scheduleEnabled: bool = False
    scheduleSince: str = ""
    scheduleCursor: str = ""
    scheduleLastRun: str = ""
    scheduleNextRun: str = ""
    scheduleWeekday: int = Field(default=0, ge=0, le=6)
    scheduleDay: int = Field(default=1, ge=1, le=31)

    @validator("startTime", "endTime", "scheduleSince", "scheduleCursor",
               "scheduleLastRun", "scheduleNextRun")
    def normalize_datetime_fields(cls, value: str) -> str:
        try:
            return str(normalize_datetime(value) or "")
        except ValueError as exc:
            raise ValueError("时间必须是有效的日期时间") from exc


class GroupDelete(BaseModel):
    groupId: str = Field(min_length=1)


class WelinkCliStatus(BaseModel):
    installed: bool
    ready: bool
    message: str
    conversationCount: int = 0


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
    # Kept for protocol compatibility. WeLink's msgTotalCount is only the
    # current page size, so the agent cannot provide a history total here.
    totalHint: int = 0


class MessageSelection(BaseModel):
    mode: Literal["all", "explicit"] = "all"
    excludedMessageIds: list[str] = Field(default_factory=list)
    selectedMessageIds: list[str] = Field(default_factory=list)


class ExtractRequest(MessageQuery):
    skillId: str = "welink-experience-extractor"
    extractMode: Literal["direct", "draft"] = "direct"
    uploadBy: str = Field(min_length=1)
    selection: MessageSelection = Field(default_factory=MessageSelection)


class ExtractCancelRequest(BaseModel):
    taskId: str = ''
    groupId: str = ''


class ScheduleSetRequest(BaseModel):
    groupId: str = Field(min_length=1)
    uploadBy: str = Field(min_length=1)
    skillId: str = "welink-experience-extractor"
    extractMode: Literal["direct", "draft"] = "direct"
    scheduleFreq: Literal["daily", "weekly", "monthly", "custom"] = "daily"
    scheduleTime: str = "09:00:00"
    scheduleCron: str = ""
    since: Optional[str] = None

    @validator("since")
    def normalize_since(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            normalized = normalize_datetime(value)
        except ValueError as exc:
            raise ValueError("since 必须是有效的日期时间") from exc
        if not normalized:
            raise ValueError("since 不能为空")
        return str(normalized)


class ScheduleCancelRequest(BaseModel):
    groupId: str = Field(min_length=1)


class EmailRule(BaseModel):
    id: str = ""
    name: str = Field(min_length=1)
    subjectKeywords: list[str] = Field(default_factory=list)
    bodyKeywords: list[str] = Field(default_factory=list)
    senders: list[str] = Field(default_factory=list)
    logic: Literal["OR", "AND"] = "OR"
    enabled: bool = True

    @validator("name")
    def normalize_rule_name(cls, value: str) -> str:
        return value.strip()

    @validator("subjectKeywords", "bodyKeywords", "senders")
    def normalize_rule_values(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(
            str(item).strip() for item in value if str(item).strip()))


class EmailConfig(BaseModel):
    folders: list[str] = Field(default_factory=list)
    rules: list[EmailRule] = Field(default_factory=list)
    blacklist: list[EmailRule] = Field(default_factory=list)
    skillId: str = "email-experience-extractor"
    extractMode: Literal["direct", "draft"] = "direct"
    uploadBy: str = ""
    scheduleEnabled: bool = False
    scheduleFreq: Literal["daily", "weekly", "monthly", "custom"] = "daily"
    scheduleTime: str = "09:00:00"
    scheduleCron: str = ""
    scheduleSince: str = ""
    scheduleCursor: str = ""
    scheduleNextRun: str = ""
    scheduleWeekday: int = Field(default=0, ge=0, le=6)
    scheduleDay: int = Field(default=1, ge=1, le=31)

    @validator("folders")
    def normalize_folders(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(
            str(item).strip() for item in value if str(item).strip()))

    @validator("scheduleSince", "scheduleCursor", "scheduleNextRun")
    def normalize_email_datetimes(cls, value: str) -> str:
        try:
            return str(normalize_datetime(value) or "")
        except ValueError as exc:
            raise ValueError("时间必须是有效的日期时间") from exc


class EmailListRequest(BaseModel):
    folders: list[str] = Field(default_factory=list)
    startTime: Optional[str] = None
    endTime: Optional[str] = None
    query: str = ""
    matchedOnly: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class EmailDetailRequest(BaseModel):
    itemId: str = Field(min_length=1)


class EmailSelection(BaseModel):
    mode: Literal["all", "explicit"] = "explicit"
    excludedItemIds: list[str] = Field(default_factory=list)
    selectedItemIds: list[str] = Field(default_factory=list)


class EmailExtractRequest(BaseModel):
    folders: list[str] = Field(default_factory=list)
    startTime: Optional[str] = None
    endTime: Optional[str] = None
    query: str = ""
    matchedOnly: bool = False
    skillId: str = "email-experience-extractor"
    extractMode: Literal["direct", "draft"] = "direct"
    uploadBy: str = Field(min_length=1)
    selection: EmailSelection = Field(default_factory=EmailSelection)


class EmailScheduleSetRequest(BaseModel):
    folders: list[str] = Field(default_factory=list)
    uploadBy: str = Field(min_length=1)
    skillId: str = "email-experience-extractor"
    extractMode: Literal["direct", "draft"] = "direct"
    scheduleFreq: Literal["daily", "weekly", "monthly", "custom"] = "daily"
    scheduleTime: str = "09:00:00"
    scheduleCron: str = ""
    since: Optional[str] = None

    @validator("since")
    def normalize_email_since(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = normalize_datetime(value)
        if not normalized:
            raise ValueError("since 不能为空")
        return str(normalized)
