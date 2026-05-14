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

_LOGIN_URL = 'https://clouddrive.huawei.com/api/v2/login'


class DownloadMsgFile(BaseModel):
    download_result: bool
    download_error_msg: Optional[str] = None
    file_content: Optional[bytes] = None


def _get_token():
    resp = requests.post(
        url=_LOGIN_URL,
        json={
            "loginName": CLOUDDRIVE_ACCOUNT,
            "password":  CLOUDDRIVE_PASSWORD,
            "appId":     "espace",
            "domain":    "huawei",
        },
        headers={
            "Content-Type":     "application/json",
            "x-device-sn":      "0123456789",
            "x-device-type":    "web",
            "x-client-version": "2.0",
            "x-device-os":      "EulerOS",
            "x-device-name":    "huawei",
        },
        verify=False,
        timeout=10,
    )
    if resp.status_code == 200:
        return True, json.loads(resp.text).get('token', '')
    return False, f"get token failed: {resp.text}"


def one_box_download(down_url: str, extraction_code: str) -> DownloadMsgFile:
    ok, token = _get_token()
    if not ok:
        return DownloadMsgFile(download_result=False, download_error_msg=token)

    date = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
    str_sha = hashlib.sha256((extraction_code + "_sep_" + date).encode('utf-8')).hexdigest()
    plain_access_code = (
        base64.encodebytes(str_sha.encode('utf-8')).decode().strip().replace('\n', '')
    )

    resp = requests.post(
        url=down_url,
        headers={'Authorization': token, 'Date': date, 'Content-Type': 'application/json'},
        json={"plainAccessCode": plain_access_code},
        verify=False,
        timeout=30,
    )
    if resp.status_code == 200:
        return DownloadMsgFile(download_result=True, file_content=resp.content)
    return DownloadMsgFile(
        download_result=False,
        download_error_msg=f"download failed: {resp.status_code}",
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
