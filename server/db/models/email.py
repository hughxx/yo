from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from server.db.models import Base, _now
import json as _json


class Collection(Base):
    __tablename__ = "t_collection_namespaces"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(200), nullable=False, unique=True, index=True)
    description = Column(String(500), default="")
    created_at  = Column(DateTime, default=_now)


class Email(Base):
    __tablename__ = "t_collection_emails"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    conversation_topic = Column(String(500), nullable=False, unique=True, index=True)
    subject            = Column(Text, default="")
    sender_name        = Column(String(500), default="")
    received_time      = Column(DateTime)
    html_body          = Column(Text(4294967295), default="")   # LONGTEXT
    upload_by          = Column(String(100), default="")
    created_at         = Column(DateTime, default=_now)
    updated_at         = Column(DateTime, default=_now, onupdate=_now)


class EmailNamespace(Base):
    __tablename__  = "t_collection_email_namespaces"
    __table_args__ = (UniqueConstraint("email_id", "namespace_id", name="uq_email_namespace"),)

    id           = Column(Integer, primary_key=True, autoincrement=True)
    email_id     = Column(Integer, nullable=False, index=True)
    namespace_id = Column(Integer, nullable=False, index=True)
    status       = Column(String(20), default="pending")   # pending / done / failed


class EmailRule(Base):
    __tablename__ = "t_collection_email_rules"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    namespace_id  = Column(Integer, nullable=False, index=True)
    name          = Column(String(200), nullable=False)
    keywords      = Column(Text, default="[]")   # JSON 数组
    body_keywords = Column(Text, default="[]")   # JSON 数组
    senders       = Column(Text, default="[]")   # JSON 数组
    logic         = Column(String(10), default="OR")   # OR / AND
    enabled       = Column(Integer, default=1)         # 1=启用 0=禁用
    created_at    = Column(DateTime, default=_now)

    def to_dict(self):
        return {
            "id":            self.id,
            "name":          self.name,
            "keywords":      _json.loads(self.keywords      or "[]"),
            "body_keywords": _json.loads(self.body_keywords or "[]"),
            "senders":       _json.loads(self.senders       or "[]"),
            "logic":         self.logic,
            "enabled":       bool(self.enabled),
        }


class ImageCache(Base):
    __tablename__ = "t_collection_image_cache"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    hash       = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hex
    url        = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)
