from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from typing import Callable
from urllib.parse import urlparse

import requests

from . import __version__
from .config import Settings


logger = logging.getLogger(__name__)


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})(?:[-+].*)?", value.strip())
    if not match:
        raise ValueError(f"无效版本号：{value}")
    return tuple(int(part) for part in match.group(1).split("."))


@dataclass(frozen=True)
class UpdateStatus:
    currentVersion: str
    latestVersion: str = ""
    updateAvailable: bool = False
    downloadUrl: str = ""
    releaseNotes: tuple[str, ...] = ()
    minimumSupportedVersion: str = ""
    forceUpdate: bool = False
    configured: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UpdateRuntimeStatus:
    phase: str = "idle"
    progress: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class UpdateManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._status = UpdateStatus(currentVersion=__version__)
        self._runtime = UpdateRuntimeStatus()
        self._installer: Callable[[UpdateStatus], None] | None = None

    def check(self) -> UpdateStatus:
        status = check_for_update(self.settings)
        with self._lock:
            self._status = status
            if self._runtime.phase == "idle":
                self._runtime = UpdateRuntimeStatus(phase="available" if status.updateAvailable else "idle")
        return status

    def set_installer(self, installer: Callable[[UpdateStatus], None]) -> None:
        self._installer = installer

    def request_install(self) -> dict:
        with self._lock:
            status = self._status
            installer = self._installer
        if not status.updateAvailable:
            status = self.check()
        if not status.updateAvailable:
            raise ValueError("当前已是最新版本")
        if installer is None:
            raise RuntimeError("桌面升级器尚未就绪")
        installer(status)
        return self.snapshot()

    def set_runtime(self, phase: str, progress: int = 0,
                    error: str = "") -> None:
        with self._lock:
            self._runtime = UpdateRuntimeStatus(
                phase=phase, progress=max(0, min(100, progress)),
                error=error)

    @property
    def forced(self) -> bool:
        with self._lock:
            return self._status.forceUpdate and self._status.updateAvailable

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._status.to_dict(), **self._runtime.to_dict()}


def check_for_update(settings: Settings) -> UpdateStatus:
    if not settings.update_enabled:
        return UpdateStatus(currentVersion=__version__)
    config_url = settings.update_config_url.strip()
    config_key = settings.update_config_key.strip()
    if not config_url or not config_key:
        return UpdateStatus(currentVersion=__version__)
    if urlparse(config_url).scheme != "https":
        raise ValueError("配置中心地址必须使用 HTTPS")
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        config_url, params={"key": config_key}, timeout=10, verify=False)
    response.raise_for_status()
    envelope = response.json()
    raw_manifest = ((envelope.get("data") or {}).get("configVal")
                    if isinstance(envelope, dict) else None)
    if not isinstance(raw_manifest, str) or not raw_manifest.strip():
        raise ValueError("配置中心未返回 data.configVal")
    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        raise ValueError("配置中心 configVal 不是合法 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("版本配置必须是 JSON 对象")
    if manifest.get("enabled", True) is False:
        return UpdateStatus(currentVersion=__version__, configured=True)
    latest = str(manifest.get("latestVersion") or "").strip()
    minimum = str(manifest.get("minimumSupportedVersion") or "").strip()
    download_url = str(manifest.get("downloadUrl") or "").strip()
    notes_value = manifest.get("releaseNotes") or []
    if isinstance(notes_value, str):
        notes = (notes_value,)
    elif isinstance(notes_value, list) and all(isinstance(item, str) for item in notes_value):
        notes = tuple(notes_value)
    else:
        raise ValueError("releaseNotes 必须是字符串或字符串数组")
    if not latest:
        raise ValueError("版本配置缺少 latestVersion")
    if not minimum:
        raise ValueError("版本配置缺少 minimumSupportedVersion")
    if _version_tuple(minimum) > _version_tuple(latest):
        raise ValueError("minimumSupportedVersion 不能高于 latestVersion")
    available = _version_tuple(latest) > _version_tuple(__version__)
    below_minimum = _version_tuple(__version__) < _version_tuple(minimum)
    force_update = below_minimum or (
        bool(manifest.get("forceUpdate", False)) and available)
    if available and urlparse(download_url).scheme not in {"http", "https"}:
        raise ValueError("更新包地址必须使用 HTTP/HTTPS")
    return UpdateStatus(
        currentVersion=__version__, latestVersion=latest,
        updateAvailable=available, downloadUrl=download_url if available else "",
        releaseNotes=notes,
        minimumSupportedVersion=minimum, forceUpdate=force_update,
        configured=True)
