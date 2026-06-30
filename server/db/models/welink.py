from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT

from server.db.models import Base, _now

# MySQL→LONGTEXT，GaussDB/PG→TEXT（无长度）
_LONGTEXT = Text().with_variant(LONGTEXT, "mysql")


class WelinkRule(Base):
    __tablename__ = "t_collection_welink_rules"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    group_id   = Column(String(100), nullable=False, unique=True, index=True)
    group_name = Column(String(200), default="")
    enabled    = Column(Integer, default=1)
    created_at = Column(DateTime, default=_now)

    def to_dict(self):
        return {
            "id":         self.id,
            "group_id":   self.group_id,
            "group_name": self.group_name,
            "enabled":    bool(self.enabled),
        }


class WelinkChatlog(Base):
    __tablename__ = "t_collection_welink_chatlogs"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    chat_id    = Column(String(200), nullable=False, unique=True, index=True)  # "{group_id}_{start_msg_id}"
    group_id   = Column(String(100), nullable=False, index=True)
    group_name = Column(String(200), default="")
    start_time = Column(DateTime)
    end_time   = Column(DateTime)
    html_body      = Column(_LONGTEXT, default="")
    markdown_body  = Column(_LONGTEXT, default="")   # 客户端直传的 markdown（非按天路径有则直接用）
    upload_by      = Column(String(100), default="")
    process_status = Column(String(20), default="pending")
    is_daily       = Column(Integer, default=0)
    created_at     = Column(DateTime, default=_now)
    updated_at     = Column(DateTime, default=_now, onupdate=_now)
