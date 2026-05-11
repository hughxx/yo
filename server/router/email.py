import json
import logging

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from server.db.models.email import Collection, Email, EmailNamespace, EmailRule
from server.service.email_service import get_or_create_collection, img_to_url, upsert_email
from server.service.experience_service import process_email
from server.db.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email")


@router.get("/ping")
def ping():
    return {"Success": True, "Message": "pong"}


@router.post("/receive")
async def receive_email(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        data = await request.json()
    except Exception:
        return {"Success": False, "Message": "Invalid JSON"}

    topic = data.get("ConversationTopic", "")[:60]
    logger.info("receive: topic=%r", topic)

    ok, msg, process_kwargs = upsert_email(db, data, force=bool(data.get("Force", False)))

    if ok and process_kwargs:
        logger.info("background_task scheduled: topic=%r", topic)
        background_tasks.add_task(process_email, **process_kwargs)
    else:
        logger.info("no background_task: ok=%s msg=%r", ok, msg)

    return {"Success": ok, "Message": msg}


@router.get("/namespaces")
def list_namespaces(db: Session = Depends(get_db)):
    rows = db.query(Collection).order_by(Collection.name).all()
    return [{"id": r.id, "name": r.name, "description": r.description} for r in rows]


@router.post("/parse_status")
async def get_parse_status(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception:
        return {}

    topics         = [t.strip() for t in data.get("topics", []) if t and t.strip()]
    namespace_name = (data.get("namespace", "") or "").strip()
    if not topics or not namespace_name:
        return {}

    col = db.query(Collection).filter_by(name=namespace_name).first()
    if col is None:
        return {}

    rows = (
        db.query(Email.conversation_topic, EmailNamespace.status)
        .join(EmailNamespace, EmailNamespace.email_id == Email.id)
        .filter(
            Email.conversation_topic.in_(topics),
            EmailNamespace.namespace_id == col.id,
        )
        .all()
    )
    return {topic: status for topic, status in rows}


# ── 云端规则 CRUD ─────────────────────────────────────────

@router.get("/rules")
def list_rules(namespace: str = "", db: Session = Depends(get_db)):
    col = db.query(Collection).filter_by(name=namespace).first()
    if not col:
        return []
    rules = (db.query(EmailRule)
               .filter_by(namespace_id=col.id)
               .order_by(EmailRule.created_at)
               .all())
    return [r.to_dict() for r in rules]


@router.post("/rules")
async def create_rule(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    namespace = (data.get("namespace") or "").strip()
    name      = (data.get("name")      or "").strip()
    if not namespace or not name:
        return {"success": False, "message": "namespace 和 name 不能为空"}
    col  = get_or_create_collection(db, namespace)
    rule = EmailRule(
        namespace_id  = col.id,
        name          = name,
        keywords      = json.dumps(data.get("keywords",      []), ensure_ascii=False),
        body_keywords = json.dumps(data.get("body_keywords", []), ensure_ascii=False),
        senders       = json.dumps(data.get("senders",       []), ensure_ascii=False),
        logic         = data.get("logic", "OR"),
        enabled       = 1,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule.to_dict()


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    rule = db.query(EmailRule).filter_by(id=rule_id).first()
    if not rule:
        return {"success": False, "message": "规则不存在"}
    if "name"          in data: rule.name          = data["name"]
    if "keywords"      in data: rule.keywords      = json.dumps(data["keywords"],      ensure_ascii=False)
    if "body_keywords" in data: rule.body_keywords = json.dumps(data["body_keywords"], ensure_ascii=False)
    if "senders"       in data: rule.senders       = json.dumps(data["senders"],       ensure_ascii=False)
    if "logic"         in data: rule.logic         = data["logic"]
    if "enabled"       in data: rule.enabled       = 1 if data["enabled"] else 0
    db.commit()
    return rule.to_dict()


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(EmailRule).filter_by(id=rule_id).first()
    if rule:
        db.delete(rule)
        db.commit()
    return {"success": True}


# ── 用户信息搜索 ──────────────────────────────────────────

_HW_USERINFO_URL = "https://fuyao.rnd.huawei.com/config-service/config-center/hw-userinfo"


@router.get("/userinfo")
def search_userinfo(info: str = ""):
    if not info.strip():
        return []
    try:
        resp = requests.get(_HW_USERINFO_URL, params={"info": info}, timeout=10, verify=False)
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        return [{"label": r.get("name", ""), "value": r.get("sAMAccountName", "")} for r in rows]
    except Exception:
        logger.warning("userinfo search failed for info=%r", info, exc_info=True)
        return []


@router.post("/upload_image")
async def upload_image(
    file: UploadFile = File(...),
    filename: str = Form(None),
):
    file_name = (filename or file.filename or "image.png").strip()
    logger.info("upload_image: %s", file_name)
    try:
        url = img_to_url(await file.read(), file_name)
        logger.info("upload_image ok: %s", url)
        return {"Success": True, "Url": url}
    except Exception as e:
        logger.exception("upload_image failed: %s", file_name)
        return {"Success": False, "Message": str(e)}
