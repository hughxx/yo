import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from server.db.db import get_db
from server.db.models.welink import WelinkChatlog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/welink")


@router.get("/ping")
def ping():
    return {"Success": True, "Message": "pong"}


@router.post("/receive")
async def receive_chatlog(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception:
        return {"Success": False, "Message": "Invalid JSON"}

    chat_id = (data.get("ChatId") or "").strip()
    if not chat_id:
        return {"Success": False, "Message": "ChatId is required"}

    logger.info("welink receive: chat_id=%r", chat_id)

    existing = db.query(WelinkChatlog).filter_by(chat_id=chat_id).first()
    if existing:
        logger.info("welink duplicate: chat_id=%r upload_by=%r", chat_id, data.get("UploadBy"))
        return {"Success": True, "Message": "Already exists", "Duplicate": True}

    row = WelinkChatlog(
        chat_id    = chat_id,
        group_id   = (data.get("GroupId")   or "").strip(),
        group_name = (data.get("GroupName") or "").strip(),
        start_time = _parse_ms(data.get("StartTime")),
        end_time   = _parse_ms(data.get("EndTime")),
        html_body  = data.get("HtmlBody", ""),
        upload_by  = (data.get("UploadBy") or "").strip(),
    )
    db.add(row)
    db.commit()
    logger.info("welink saved: chat_id=%r", chat_id)
    return {"Success": True, "Message": "Received successfully", "Duplicate": False}


def _parse_ms(value):
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None
