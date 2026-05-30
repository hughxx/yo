from sqlalchemy import Column, DateTime, Integer, String, Text

from server.db.models import Base, _now


class ProcessLog(Base):
    """后端后台处理的统一错误日志（email / welink 共用）。"""

    __tablename__ = "t_process_logs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    source       = Column(String(20),  nullable=False, default="", index=True)  # email / welink / welink_daily
    ref_key      = Column(String(500), nullable=False, default="")               # conversation_topic 或 chat_id
    scope        = Column(String(200), nullable=False, default="")               # namespace_name 或 group_name
    error_type   = Column(String(100), nullable=False, default="", index=True)   # 异常类名
    error_detail = Column(Text,        default="")                               # 完整 traceback
    created_at   = Column(DateTime, default=_now, index=True)
