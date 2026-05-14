import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from server.db.db import get_db
from server.db.models.welink import WelinkChatlog, WelinkRule
from server.service.welink_service import process_chatlog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/welink")


@router.get("/ping")
def ping():
    return {"Success": True, "Message": "pong"}


# ── 群聊规则 CRUD ──────────────────────────────────────────────

@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    rows = db.query(WelinkRule).order_by(WelinkRule.created_at).all()
    return [r.to_dict() for r in rows]


@router.post("/rules")
async def create_rule(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    group_id = (data.get("group_id") or "").strip()
    if not group_id:
        return {"success": False, "message": "group_id 不能为空"}
    if db.query(WelinkRule).filter_by(group_id=group_id).first():
        return {"success": False, "message": "该群聊已存在"}
    rule = WelinkRule(
        group_id   = group_id,
        group_name = (data.get("group_name") or "").strip(),
        enabled    = 1,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule.to_dict()


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    rule = db.query(WelinkRule).filter_by(id=rule_id).first()
    if not rule:
        return {"success": False, "message": "规则不存在"}
    if "group_name" in data:
        rule.group_name = data["group_name"]
    if "enabled" in data:
        rule.enabled = 1 if data["enabled"] else 0
    db.commit()
    return rule.to_dict()


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(WelinkRule).filter_by(id=rule_id).first()
    if rule:
        db.delete(rule)
        db.commit()
    return {"success": True}


# ── 聊天记录上传 ───────────────────────────────────────────────

@router.post("/receive")
async def receive_chatlog(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        data = await request.json()
    except Exception:
        return {"Success": False, "Message": "Invalid JSON"}

    chat_id = (data.get("ChatId") or "").strip()
    if not chat_id:
        return {"Success": False, "Message": "ChatId is required"}

    logger.info("welink receive: chat_id=%r", chat_id)

    if db.query(WelinkChatlog).filter_by(chat_id=chat_id).first():
        logger.info("welink duplicate: chat_id=%r", chat_id)
        return {"Success": True, "Message": "Already exists", "Duplicate": True}

    html_body  = data.get("HtmlBody", "")
    group_name = (data.get("GroupName") or "").strip()
    upload_by  = (data.get("UploadBy") or "").strip()

    row = WelinkChatlog(
        chat_id    = chat_id,
        group_id   = (data.get("GroupId") or "").strip(),
        group_name = group_name,
        start_time = _parse_ms(data.get("StartTime")),
        end_time   = _parse_ms(data.get("EndTime")),
        html_body  = html_body,
        upload_by  = upload_by,
        process_status = "pending",
    )
    db.add(row)
    db.commit()
    logger.info("welink saved: chat_id=%r", chat_id)

    if html_body:
        background_tasks.add_task(
            process_chatlog,
            html_body  = html_body,
            group_name = group_name,
            chat_id    = chat_id,
            upload_by  = upload_by,
        )

    return {"Success": True, "Message": "Received successfully", "Duplicate": False}



def _parse_ms(value):
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None
