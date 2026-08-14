from __future__ import annotations

import ctypes
import logging
import json
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__
from .app import create_app
from .config import Settings
from .updates import check_for_update


logger = logging.getLogger(__name__)


def asset_path(name: str) -> Path:
    return Path(__file__).with_name("assets") / name


def _native_notice(message: str, title: str = "CoreInsight Local Toolkit") -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)
    except Exception:
        logger.warning("desktop notice: %s", message)


def _shell_open_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "open", str(path), None, None, 1)
    if result <= 32:
        raise OSError(f"ShellExecuteW 返回 {result}")


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _activate_existing(port: int) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1) as response:
            health = json.loads(response.read().decode("utf-8"))
        if health.get("service") != "coreinsight-local-toolkit":
            return False
    except (OSError, ValueError, urllib.error.URLError):
        return False

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/desktop/show", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def run_desktop(settings: Settings) -> None:
    import pystray
    from PIL import Image
    from .win32_floating import (
        FloatingWindow, WM_APP_ABOUT, WM_APP_EXIT, WM_APP_SHOW)

    if _port_is_open(settings.port):
        if _activate_existing(settings.port):
            logger.info("existing toolkit instance activated port=%d", settings.port)
        else:
            _native_notice(
                f"本地端口 {settings.port} 已被其他程序占用，CoreInsight Local Toolkit 无法启动。\n\n"
                "请关闭占用该端口的程序，或通过 COREINSIGHT_AGENT_PORT 指定其他端口。")
            logger.error("local port is already occupied port=%d", settings.port)
        return

    ui_actions: queue.SimpleQueue[str] = queue.SimpleQueue()
    application = create_app(settings)

    @application.post("/desktop/show", include_in_schema=False)
    def activate_desktop() -> dict[str, bool]:
        ui_actions.put("show")
        return {"ok": True}

    server = uvicorn.Server(uvicorn.Config(
        application, host=settings.host, port=settings.port,
        log_level="info", log_config=None))
    server_thread = threading.Thread(
        target=server.run, name="coreinsight-http", daemon=True)
    server_thread.start()
    deadline = time.monotonic() + 10
    while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        server_thread.join(timeout=3)
        _native_notice(f"本地服务启动失败，请查看日志：{settings.data_dir / 'logs'}")
        return

    local_url = f"http://127.0.0.1:{settings.port}/demo/"
    email_url = settings.email_url or settings.portal_url
    chat_url = settings.chat_url or local_url
    source_image = Image.open(asset_path("icon.png")).convert("RGBA")

    def open_url(url: str) -> None:
        webbrowser.open(url)

    def show_about(*_args) -> None:
        _native_notice(
            f"CoreInsight Local Toolkit\n版本：{__version__}\n"
            f"本地服务：http://127.0.0.1:{settings.port}",
            "关于 CoreInsight Local Toolkit")

    def open_logs(*_args) -> None:
        log_dir = settings.data_dir / "logs"
        try:
            _shell_open_directory(log_dir)
            logger.info("log directory opened path=%s", log_dir)
        except Exception as exc:
            logger.exception("open log directory failed path=%s", log_dir)
            _native_notice(f"无法打开日志目录：\n{log_dir}\n\n{exc}")

    exiting = threading.Event()

    def check_update(*_args) -> None:
        def worker() -> None:
            try:
                status = check_for_update(settings)
                if not status.configured:
                    message = "尚未配置更新信息"
                elif status.forceUpdate:
                    message = f"当前版本已停用，请更新到 {status.latestVersion}"
                elif status.updateAvailable:
                    message = f"发现新版本 {status.latestVersion}"
                else:
                    message = f"当前已是最新版本 {status.currentVersion}"
                tray.notify(message, "CoreInsight Local Toolkit")
            except Exception as exc:
                logger.exception("update check failed")
                tray.notify(f"版本检查失败：{exc}", "CoreInsight Local Toolkit")
        threading.Thread(target=worker, name="update-check", daemon=True).start()

    try:
        floating = FloatingWindow(source_image, {
            "portal": lambda: open_url(settings.portal_url),
            "email": lambda: open_url(email_url),
            "chat": lambda: open_url(chat_url),
            "logs": open_logs,
            "update": check_update,
            "about": show_about,
        })
    except Exception:
        server.should_exit = True
        server_thread.join(timeout=10)
        raise

    def process_ui_actions() -> None:
        while not exiting.is_set():
            try:
                action = ui_actions.get(timeout=0.2)
            except queue.Empty:
                continue
            if action == "show":
                floating.post(WM_APP_SHOW)

    action_thread = threading.Thread(
        target=process_ui_actions, name="desktop-actions", daemon=True)
    action_thread.start()

    tray = pystray.Icon(
        "coreinsight-local-toolkit", source_image,
        "CoreInsight Local Toolkit",
        menu=pystray.Menu(
            pystray.MenuItem("云见主页", lambda *_: open_url(settings.portal_url)),
            pystray.MenuItem("邮件提取", lambda *_: open_url(email_url)),
            pystray.MenuItem("聊天记录提取", lambda *_: open_url(chat_url)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开日志目录", open_logs),
            pystray.MenuItem("检查更新", check_update),
            pystray.MenuItem("关于", lambda *_: floating.post(WM_APP_ABOUT)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示悬浮图标", lambda *_: floating.post(WM_APP_SHOW), default=True),
            pystray.MenuItem("退出", lambda *_: floating.post(WM_APP_EXIT)),
        ),
    )
    tray_thread = threading.Thread(target=tray.run, name="coreinsight-tray", daemon=True)
    tray_thread.start()
    threading.Timer(2.0, check_update).start()
    logger.info("desktop floating icon and tray started")
    try:
        floating.run()
    finally:
        exiting.set()
        server.should_exit = True
        tray.stop()
        server_thread.join(timeout=10)
        floating.dispose()
        logger.info("desktop host stopped")
