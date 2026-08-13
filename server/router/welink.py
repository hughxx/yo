import logging
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from server.db.db import get_db
from server.db.models.welink import WelinkChatlog, WelinkRule
from server.service.welink_service import process_chatlog
from server.service.welink_import_service import (
    create_import, get_import, load_complete, mark_status, messages_to_markdown,
    save_chunk,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/welink")


@router.post("/imports")
async def begin_import(request: Request):
    data = await request.json()
    try:
        meta = create_import((data.get("importId") or "").strip(), data)
        return {"Success": True, "Import": meta}
    except ValueError as exc:
        return {"Success": False, "Message": str(exc)}


@router.post("/imports/{import_id}/chunks/{index}")
async def upload_import_chunk(import_id: str, index: int, request: Request):
    data = await request.json()
    try:
        result = save_chunk(import_id, index, data.get("messages") or [])
        return {"Success": True, **result}
    except (KeyError, ValueError) as exc:
        return {"Success": False, "Message": str(exc)}


@router.post("/imports/{import_id}/complete")
async def complete_import(import_id: str, request: Request, background_tasks: BackgroundTasks,
                          db: Session = Depends(get_db)):
    data = await request.json()
    try:
        meta, messages = load_complete(import_id, int(data.get("chunkCount") or 0),
                                       int(data.get("messageCount") or 0))
    except (KeyError, ValueError) as exc:
        return {"Success": False, "Message": str(exc)}
    if not messages:
        return {"Success": False, "Message": "没有可提取的聊天消息"}
    digest = hashlib.sha1(",".join(item["id"] for item in messages).encode("utf-8")).hexdigest()[:12]
    chat_id = f"agent_{import_id}_{digest}"
    existing = db.query(WelinkChatlog).filter_by(chat_id=chat_id).first()
    if existing:
        return {"Success": True, "Message": "Already exists", "ChatId": chat_id, "Duplicate": True}
    markdown = messages_to_markdown(messages)
    row = WelinkChatlog(
        chat_id=chat_id, group_id=str(meta.get("groupId") or ""),
        group_name=str(meta.get("groupName") or ""),
        start_time=_parse_ms(messages[0].get("timestamp")),
        end_time=_parse_ms(messages[-1].get("timestamp")), markdown_body=markdown,
        upload_by=str(meta.get("uploadBy") or ""), process_status="pending", is_daily=0,
    )
    db.add(row); db.commit()
    mark_status(import_id, "processing", chat_id)
    background_tasks.add_task(
        process_chatlog, html_body="", markdown_body=markdown,
        group_id=row.group_id, group_name=row.group_name, chat_id=chat_id,
        upload_by=row.upload_by, is_daily=False,
        prompt_content=str(meta.get("promptContent") or ""),
    )
    return {"Success": True, "Message": "Upload completed", "ChatId": chat_id, "Duplicate": False}


@router.get("/imports/{import_id}")
def import_status(import_id: str, db: Session = Depends(get_db)):
    try:
        meta = get_import(import_id)
    except KeyError:
        return {"Success": False, "Message": "导入批次不存在"}
    chat_id = meta.get("chatId")
    if chat_id:
        row = db.query(WelinkChatlog).filter_by(chat_id=chat_id).first()
        if row:
            meta["status"] = row.process_status
    return {"Success": True, "Import": meta}


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

    html_body     = data.get("HtmlBody", "")
    markdown_body = data.get("MarkdownBody", "")
    group_id   = (data.get("GroupId") or "").strip()
    group_name = (data.get("GroupName") or "").strip()
    upload_by  = (data.get("UploadBy") or "").strip()
    is_daily   = bool(data.get("IsDaily", False))

    row = WelinkChatlog(
        chat_id        = chat_id,
        group_id       = group_id,
        group_name     = group_name,
        start_time     = _parse_ms(data.get("StartTime")),
        end_time       = _parse_ms(data.get("EndTime")),
        html_body      = html_body,
        markdown_body  = markdown_body,
        upload_by      = upload_by,
        process_status = "pending",
        is_daily       = 1 if is_daily else 0,
    )
    db.add(row)
    db.commit()
    logger.info("welink saved: chat_id=%r is_daily=%s", chat_id, is_daily)

    if html_body or markdown_body:
        background_tasks.add_task(
            process_chatlog,
            html_body     = html_body,
            markdown_body = markdown_body,
            group_id      = group_id,
            group_name    = group_name,
            chat_id       = chat_id,
            upload_by     = upload_by,
            is_daily      = is_daily,
        )

    return {"Success": True, "Message": "Received successfully", "Duplicate": False}



def _parse_ms(value):
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None
