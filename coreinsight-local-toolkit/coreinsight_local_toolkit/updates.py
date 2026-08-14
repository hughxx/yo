from __future__ import annotations

import re
import json
import hashlib
import logging
import os
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

from . import __version__
from .config import Settings


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
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
    sha256: str = ""
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
    packagePath: str = ""

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

    def set_runtime(self, phase: str, progress: int = 0, error: str = "",
                    package_path: str = "") -> None:
        with self._lock:
            self._runtime = UpdateRuntimeStatus(
                phase=phase, progress=max(0, min(100, progress)),
                error=error, packagePath=package_path)

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


def download_update(settings: Settings, status: UpdateStatus,
                    progress: Callable[[int], None] | None = None,
                    session: requests.Session | None = None) -> Path:
    if not status.updateAvailable or not status.downloadUrl:
        raise ValueError("没有可下载的新版本")
    update_dir = settings.data_dir / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    final_path = update_dir / f"coreinsight-local-toolkit-{status.latestVersion}.exe"
    partial_path = final_path.with_suffix(".exe.part")
    digest = hashlib.sha256()
    downloaded = 0
    own_session = session is None
    session = session or requests.Session()
    if own_session:
        session.trust_env = False
    try:
        with session.get(status.downloadUrl, stream=True, timeout=(10, 300),
                         verify=False) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            with partial_path.open("wb") as target:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    target.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress and total:
                        progress(min(99, downloaded * 100 // total))
        if downloaded < 2:
            raise ValueError("更新包为空")
        actual = digest.hexdigest().lower()
        if actual != status.sha256.lower():
            raise ValueError(f"更新包 SHA-256 校验失败：期望 {status.sha256}，实际 {actual}")
        with partial_path.open("rb") as package_file:
            signature = package_file.read(2)
        if signature != b"MZ":
            raise ValueError("更新包不是有效的 Windows EXE")
        os.replace(partial_path, final_path)
        if progress:
            progress(100)
        logger.info("update downloaded version=%s path=%s sha256=%s",
                    status.latestVersion, final_path, actual)
        return final_path
    except Exception:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("partial update cleanup failed path=%s", partial_path, exc_info=True)
        raise
    finally:
        if own_session:
            session.close()


def create_updater_script(settings: Settings, package_path: Path,
                          executable_path: Path | None = None,
                          process_ids: tuple[int, ...] | None = None) -> Path:
    executable = executable_path or Path(sys.executable).resolve()
    pids = process_ids or tuple(dict.fromkeys((os.getpid(), os.getppid())))
    update_dir = settings.data_dir / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    script_path = update_dir / "apply-update.cmd"

    def batch_value(value: Path) -> str:
        return str(value).replace("%", "%%").replace('"', '""')

    checks = "\n".join(
        f'tasklist /fi "PID eq {pid}" /nh 2>nul | findstr /r /c:"[ ]{pid}[ ]" >nul && set "RUNNING=1"'
        for pid in pids if pid > 0)
    script = f"""@echo off
setlocal
set "SOURCE={batch_value(package_path.resolve())}"
set "TARGET={batch_value(executable)}"
set "LOG={batch_value((settings.data_dir / 'logs' / 'updater.log').resolve())}"
echo [%date% %time%] updater started>>"%LOG%"
set /a ATTEMPTS=0
:wait_process
set "RUNNING="
{checks}
if not defined RUNNING goto replace
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ 120 goto wait_failed
timeout /t 1 /nobreak >nul
goto wait_process
:replace
copy /b /y "%SOURCE%" "%TARGET%" >>"%LOG%" 2>&1
if errorlevel 1 goto replace_failed
del /q "%SOURCE%" >nul 2>&1
echo [%date% %time%] update applied>>"%LOG%"
start "" "%TARGET%"
del /q "%~f0" >nul 2>&1
exit /b 0
:wait_failed
echo [%date% %time%] timed out waiting for old process>>"%LOG%"
exit /b 2
:replace_failed
echo [%date% %time%] failed to replace executable>>"%LOG%"
exit /b 3
"""
    script_path.write_text(script, encoding="utf-8-sig", newline="\r\n")
    return script_path


def launch_updater(script_path: Path) -> None:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/d", "/c", str(script_path)],
        cwd=str(script_path.parent), close_fds=True,
        creationflags=creation_flags)
    logger.info("external updater launched script=%s", script_path)
