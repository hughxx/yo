from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from .config import Settings


logger = logging.getLogger(__name__)


class CloudDriveRateLimited(RuntimeError):
    pass


class CloudDriveDownloader:
    """Share a token and download cooldown across extraction tasks."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._token = ""
        self._token_expires = 0.0
        self._blocked_until = 0.0
        self._next_request = 0.0

    @staticmethod
    def _wait(seconds: float, cancel_event=None) -> None:
        if cancel_event is not None:
            if cancel_event.wait(max(0, seconds)):
                raise RuntimeError("任务已取消")
        elif seconds > 0:
            time.sleep(seconds)

    @staticmethod
    def _retry_delay(response, attempt: int) -> float:
        value = response.headers.get("Retry-After", "")
        try:
            delay = float(value)
            if math.isfinite(delay):
                return max(1.0, delay)
        except (TypeError, ValueError):
            pass
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(1.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return float(2 ** (attempt + 1))

    def _post(self, url: str, cancel_event=None, **kwargs):
        for attempt in range(3):
            self._wait(self._next_request - time.monotonic(), cancel_event)
            try:
                response = requests.post(url, verify=False, **kwargs)
            finally:
                self._next_request = time.monotonic() + 1.0
            if response.status_code != 429:
                return response
            delay = self._retry_delay(response, attempt)
            response.close()
            # Avoid repeating three requests for every remaining attachment.
            if attempt == 2 or delay > 60:
                cooldown = max(60.0, delay)
                self._blocked_until = time.monotonic() + cooldown
                logger.warning("CloudDrive rate limited; cooldown_seconds=%.0f", cooldown)
                raise CloudDriveRateLimited(
                    f"CloudDrive 附件下载被限流，已暂停请求，请 {math.ceil(cooldown)} 秒后重试")
            logger.warning("CloudDrive returned 429; retry=%d delay_seconds=%.0f",
                           attempt + 1, delay)
            self._wait(delay, cancel_event)
        raise AssertionError("unreachable")

    def _get_token(self, cancel_event=None) -> str:
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        response = self._post(
            "https://clouddrive.huawei.com/api/v2/token", cancel_event,
            json={"appId": "espace", "domain": "huawei",
                  "loginName": self.settings.clouddrive_account,
                  "password": self.settings.clouddrive_password},
            headers={"Content-Type": "application/json",
                     "x-device-sn": "coreinsight-local-toolkit", "x-device-type": "web",
                     "x-device-os": "win10", "x-device-name": "coreinsight",
                     "x-client-version": "10"}, timeout=60)
        response.raise_for_status()
        token = response.json().get("token", "")
        if not isinstance(token, str) or not token:
            raise RuntimeError("CloudDrive 登录未返回 token，请检查附件下载账号配置")
        self._token = token
        self._token_expires = time.monotonic() + 900
        return token

    def download(self, download_url: str, extraction_code: str,
                 cancel_event=None) -> bytes:
        while not self._lock.acquire(timeout=0.1):
            self._wait(0, cancel_event)
        try:
            self._wait(0, cancel_event)
            remaining = self._blocked_until - time.monotonic()
            if remaining > 0:
                raise CloudDriveRateLimited(
                    f"CloudDrive 附件下载仍在限流，请 {math.ceil(remaining)} 秒后重试")
            authorization = (
                f"/:um_begin{{{download_url}|File|123|attachment|0|;;{extraction_code}"
                "|isOriginalImg:0}}/:um_end")
            for attempt in range(2):
                token = self._get_token(cancel_event)
                response = self._post(
                    "https://clouddrive.huawei.com/imchat/api/v3/links/imdownload",
                    cancel_event,
                    headers={"Authorization": token, "Content-Type": "application/json"},
                    json={"imAuthorization": authorization}, timeout=300)
                if response.status_code == 401:
                    self._token = ""
                    if attempt == 0:
                        response.close()
                        continue
                response.raise_for_status()
                self._wait(0, cancel_event)
                return response.content
            raise AssertionError("unreachable")
        finally:
            self._lock.release()
