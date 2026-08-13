from __future__ import annotations

import re
import json
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

import requests

from . import __version__
from .config import Settings


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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
    sha256: str = ""
    releaseNotes: tuple[str, ...] = ()
    minimumSupportedVersion: str = ""
    forceUpdate: bool = False
    configured: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def check_for_update(settings: Settings) -> UpdateStatus:
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
    sha256 = str(manifest.get("sha256") or "").strip().lower()
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
    if available:
        if urlparse(download_url).scheme != "https":
            raise ValueError("更新包地址必须使用 HTTPS")
        if not _SHA256_RE.fullmatch(sha256):
            raise ValueError("更新清单缺少有效的 SHA-256")
    return UpdateStatus(
        currentVersion=__version__, latestVersion=latest,
        updateAvailable=available, downloadUrl=download_url if available else "",
        sha256=sha256 if available else "", releaseNotes=notes,
        minimumSupportedVersion=minimum, forceUpdate=force_update,
        configured=True)
