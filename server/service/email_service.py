import re
from datetime import datetime, timezone

from server.db.models import _now
from server.db.models.email import Collection, Email, EmailNamespace
from server.service.config_service import get_or_create_collection


# ==================== 时间处理 ====================

def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return _normalize_time(value)

    m = re.match(r"/Date\((-?\d+)([+-]\d{4})?\)/", str(value))
    if m:
        ms = int(m.group(1))
        return _normalize_time(
            datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        )

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return _normalize_time(datetime.strptime(value, fmt))
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(value)
        return _normalize_time(dt.replace(tzinfo=None) if dt.tzinfo else dt)
    except Exception:
        return None


def _normalize_time(value):
    return value.replace(microsecond=0) if value else None


# ==================== 邮件业务 ====================

def upsert_email(db, data: dict, force: bool = False):
    """Returns (ok, msg, process_kwargs | None)."""
    conversation_topic = (data.get("ConversationTopic") or "").strip()
    if not conversation_topic:
        return False, "ConversationTopic is required", None

    user_id        = (data.get("UserId")    or "").strip()
    namespace_name = (data.get("Namespace") or "").strip()
    received_time  = parse_time(data.get("ReceivedTime"))
    html_body      = data.get("HtmlBody", "")
    markdown_body  = data.get("MarkdownBody", "")
    subject        = data.get("Subject", "")

    should_process  = False
    content_updated = False

    email = db.query(Email).filter_by(conversation_topic=conversation_topic).first()
    if email is None:
        email = Email(
            conversation_topic = conversation_topic,
            subject            = subject,
            sender_name        = data.get("SenderName", ""),
            received_time      = received_time,
            html_body          = html_body,
            markdown_body      = markdown_body,
            upload_by          = user_id,
        )
        db.add(email)
        db.flush()
        should_process = True
    elif force:
        email.subject       = subject
        email.sender_name   = data.get("SenderName", "")
        email.html_body     = html_body
        email.markdown_body = markdown_body
        email.upload_by     = user_id
        email.updated_at    = _now()
        content_updated     = True
        should_process      = True
    elif received_time and (email.received_time is None or received_time > email.received_time):
        email.subject       = subject
        email.sender_name   = data.get("SenderName", "")
        email.received_time = received_time
        email.html_body     = html_body
        email.markdown_body = markdown_body
        email.upload_by     = user_id
        email.updated_at    = _now()
        content_updated     = True
        should_process      = True

    namespace_id = None
    if namespace_name:
        col = get_or_create_collection(db, namespace_name)
        namespace_id = col.id

        ns_rec = db.query(EmailNamespace).filter_by(
            email_id=email.id, namespace_id=namespace_id
        ).first()
        if ns_rec is None:
            ns_rec = EmailNamespace(email_id=email.id, namespace_id=namespace_id, status="pending")
            db.add(ns_rec)
            should_process = True
        else:
            if content_updated or force:
                ns_rec.status = "pending"
            if ns_rec.status != "done":
                should_process = True

    db.commit()

    process_kwargs = None
    if should_process and (markdown_body or html_body):
        process_kwargs = {
            "html_body":          html_body,
            "markdown_body":      markdown_body,
            "subject":            subject,
            "user_id":            user_id,
            "namespace_id":       namespace_id,
            "namespace_name":     namespace_name,
            "conversation_topic": conversation_topic,
        }
    return True, "Received successfully", process_kwargs


