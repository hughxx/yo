import asyncio
import base64
import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional

import requests
from pydantic import BaseModel

from server.db.models.email import ImageCache
from server.utils.settings import (
    CLOUDDRIVE_ACCOUNT, CLOUDDRIVE_PASSWORD,
    FILE_SERVER_URL, RAG_PIC_PUBLIC_BASE,
    OCR_URL,
)


# ── OCR ──────────────────────────────────────────────────────────

def ocr_sync(file_content: bytes, filename: str, timeout: int = 300) -> str:
    resp = requests.post(
        OCR_URL,
        files={"file": (filename, file_content)},
        timeout=timeout,
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        return data.get("result") or data.get("text") or ""
    return str(data)


async def ocr(file_content: bytes, filename: str, timeout: int = 300) -> str:
    return await asyncio.to_thread(ocr_sync, file_content, filename, timeout)


# ── CloudDrive 下载 ───────────────────────────────────────────────

_TOKEN_URL = 'https://clouddrive.huawei.com/api/v2/token'


class DownloadMsgFile(BaseModel):
    download_result: bool
    download_error_msg: Optional[str] = None
    file_content: Optional[bytes] = None


def _get_token():
    resp = requests.post(
        url=_TOKEN_URL,
        json={
            "appId": "espace",
            "domain": "huawei",
            "loginName": CLOUDDRIVE_ACCOUNT,
            "password": CLOUDDRIVE_PASSWORD,
        },
        headers={
            "Content-Type": "application/json",
            "x-device-sn": "device0123456789",
            "x-device-type": "web",
            "x-device-os": "win10",
            "x-device-name": "machinec00100000",
            "x-client-version": "10",
        },
        verify=False,
        timeout=300,
    )
    if resp.status_code == 200:
        data = resp.json()
        return True, data.get("token", "")
    return False, f"get token failed: {resp.text}"


def one_box_download(down_url: str, extraction_code: str) -> DownloadMsgFile:
    ok, token = _get_token()
    if not ok:
        return DownloadMsgFile(download_result=False, download_error_msg=token)

    im_authorization = (
        f"/:um_begin{{{down_url}"
        f"|File|123|abc.png|0|;;{extraction_code}"
        f"|isOriginalImg: 0;md5:abc123;isCrossInstance:0;emotionId:;objectId:;cdnUrl:}}/:um_end"
    )

    resp = requests.post(
        url="https://clouddrive.huawei.com/imchat/api/v3/links/imdownload",
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
        json={"imAuthorization": im_authorization},
        verify=False,
        timeout=300,
    )
    if resp.status_code == 200:
        return DownloadMsgFile(download_result=True, file_content=resp.content)
    return DownloadMsgFile(
        download_result=False,
        download_error_msg=f"download failed: {resp.status_code}, {resp.text}",
    )


# ── 图片上传 ──────────────────────────────────────────────────────

def img_to_url(file_bytes: bytes, file_name: str, db=None) -> str:
    h = hashlib.sha256(file_bytes).hexdigest()

    if db is not None:
        cached = db.query(ImageCache).filter_by(hash=h).first()
        if cached:
            return cached.url

    uuid_ = str(uuid.uuid4())
    resp = requests.post(
        f"{FILE_SERVER_URL}/rag_pic/{uuid_}",
        files={"file": (file_name, file_bytes)},
        timeout=30,
        verify=False,
    )
    resp.raise_for_status()
    url = f"{RAG_PIC_PUBLIC_BASE}/rag_pic/{uuid_}/{file_name}"

    if db is not None:
        try:
            db.add(ImageCache(hash=h, url=url))
            db.commit()
        except Exception:
            db.rollback()

    return url
