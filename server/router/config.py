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


@router.get("/version")
def client_version():
    """客户端最新版本信息。发版时改 settings 里的 CLIENT_* 即可推送给所有客户端。

    latest = 最新版本号；min = 低于此版本则强制更新；url = 下载地址；notes = 更新说明。
    用 getattr 兜默认值，settings 未配置时返回空，客户端会静默跳过。
    """
    from server.utils import settings as st
    return {
        "latest": getattr(st, "CLIENT_LATEST_VERSION", ""),
        "min":    getattr(st, "CLIENT_MIN_VERSION", ""),
        "url":    getattr(st, "CLIENT_DOWNLOAD_URL", ""),
        "notes":  getattr(st, "CLIENT_UPDATE_NOTES", ""),
    }


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
