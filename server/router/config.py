import logging

import requests
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.db.db import get_db
from server.db.models.email import Collection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/ping")
def ping():
    return {"Success": True, "Message": "pong"}


_HW_USERINFO_URL = "https://fuyao.rnd.huawei.com/config-service/config-center/hw-userinfo"


@router.get("/namespaces")
def list_namespaces(db: Session = Depends(get_db)):
    rows = db.query(Collection).order_by(Collection.name).all()
    return [{"id": r.id, "name": r.name, "description": r.description} for r in rows]


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
