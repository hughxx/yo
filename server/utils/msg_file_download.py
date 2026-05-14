import base64
import hashlib
import json
from datetime import datetime
from typing import Optional

import requests
from pydantic import BaseModel

from server.utils.settings import CLOUDDRIVE_ACCOUNT, CLOUDDRIVE_PASSWORD

_LOGIN_URL = 'https://clouddrive.huawei.com/api/v2/login'


class DownloadMsgFile(BaseModel):
    download_result: bool
    download_error_msg: Optional[str] = None
    file_content: Optional[bytes] = None


def _get_token() -> tuple[bool, str]:
    resp = requests.post(
        url=_LOGIN_URL,
        json={
            "loginName": CLOUDDRIVE_ACCOUNT,
            "password":  CLOUDDRIVE_PASSWORD,
            "appId":     "espace",
            "domain":    "huawei",
        },
        headers={
            "Content-Type":    "application/json",
            "x-device-sn":     "0123456789",
            "x-device-type":   "web",
            "x-client-version": "2.0",
            "x-device-os":     "EulerOS",
            "x-device-name":   "huawei",
        },
        verify=False,
        timeout=10,
    )
    if resp.status_code == 200:
        token = json.loads(resp.text).get('token', '')
        return True, token
    return False, f"get token failed: {resp.text}"


def one_box_download(down_url: str, extraction_code: str) -> DownloadMsgFile:
    ok, token = _get_token()
    if not ok:
        return DownloadMsgFile(download_result=False, download_error_msg=token)

    gmt_format = '%a, %d %b %Y %H:%M:%S GMT'
    date = datetime.utcnow().strftime(gmt_format)
    string_to_sign = extraction_code + "_sep_" + date
    str_sha = hashlib.sha256(string_to_sign.encode('utf-8')).hexdigest()
    plain_access_code = (
        base64.encodebytes(str_sha.encode('utf-8'))
        .decode()
        .strip()
        .replace('\n', '')
    )

    resp = requests.post(
        url=down_url,
        headers={
            'Authorization': token,
            'Date':          date,
            'Content-Type':  'application/json',
        },
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
