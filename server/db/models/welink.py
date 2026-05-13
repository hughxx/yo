from sqlalchemy import Column, DateTime, Integer, String, Text

from server.db.models import Base, _now


class WelinkChatlog(Base):
    __tablename__ = "t_welink_chatlogs"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    chat_id    = Column(String(200), nullable=False, unique=True, index=True)  # "{group_id}_{start_msg_id}"
    group_id   = Column(String(100), nullable=False, index=True)
    group_name = Column(String(200), default="")
    start_time = Column(DateTime)
    end_time   = Column(DateTime)
    html_body  = Column(Text(4294967295), default="")  # LONGTEXT
    upload_by  = Column(String(100), default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
