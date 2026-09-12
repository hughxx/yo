from __future__ import annotations

import ctypes
import logging
import json
import queue
import socket
import subprocess
import sys
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
from .environment import EnvironmentManager, PRODUCTION, TESTING
from .updates import UpdateManager, UpdateStatus


logger = logging.getLogger(__name__)
SINGLE_INSTANCE_MUTEX = "Global\\CoreInsight.LocalToolkit.Singleton"
AUTOSTART_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_SETTINGS_KEY = r"Software\CoreInsight\LocalToolkit"
AUTOSTART_VALUE_NAME = "CoreInsightLocalToolkit"
AUTOSTART_INITIALIZED_VALUE = "AutoStartInitialized"
ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5


class _SingleInstanceMutex:
    def __init__(self, name: str = SINGLE_INSTANCE_MUTEX):
        self.name = name
        self.handle = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        kernel32 = ctypes.windll.kernel32
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool,
                                 ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_bool
        handle = create_mutex(None, False, self.name)
        if not handle:
            error = kernel32.GetLastError()
            if error == ERROR_ACCESS_DENIED:
                return False
            raise ctypes.WinError(error)
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            close_handle(handle)
            return False
        self.handle = handle
        return True

    def close(self) -> None:
        if self.handle and sys.platform == "win32":
            close_handle = ctypes.windll.kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_bool
            close_handle(self.handle)
        self.handle = None


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        arguments = [str(Path(sys.executable).resolve()), "--startup"]
    else:
        arguments = [str(Path(sys.executable).resolve()), "-m",
                     "coreinsight_local_toolkit", "--startup"]
    return subprocess.list2cmdline(arguments)


def _read_autostart_command() -> str:
    if sys.platform != "win32":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return str(value or "")
    except FileNotFoundError:
        return ""


def _autostart_initialized() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, AUTOSTART_SETTINGS_KEY) as key:
            value, _kind = winreg.QueryValueEx(
                key, AUTOSTART_INITIALIZED_VALUE)
            return bool(value)
    except FileNotFoundError:
        return False


def _mark_autostart_initialized() -> None:
    import winreg
    with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, AUTOSTART_SETTINGS_KEY, 0,
            winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, AUTOSTART_INITIALIZED_VALUE, 0,
                          winreg.REG_DWORD, 1)


def _set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        raise RuntimeError("开机自启仅支持 Windows")
    import winreg
    if enabled:
        with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0,
                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ,
                              _startup_command())
    else:
        try:
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0,
                    winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
        except FileNotFoundError:
            pass
    _mark_autostart_initialized()


def _ensure_default_autostart() -> None:
    """Enable once by default and keep an enabled entry on the active EXE."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    current = _read_autostart_command()
    if not _autostart_initialized():
        _set_autostart(True)
    elif current and current != _startup_command():
        # If another packaged copy becomes the chosen primary instance, make
        # the next login start that copy instead of a stale path.
        _set_autostart(True)


def asset_path(name: str) -> Path:
    return Path(__file__).with_name("assets") / name


def _native_notice(message: str, title: str = "CoreInsight Local Toolkit") -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)
    except Exception:
        logger.warning("desktop notice: %s", message)


def open_update_page(status: UpdateStatus, update_manager: UpdateManager,
                     tray=None) -> None:
    """Open the cookie-protected download page; do not download/install locally."""
    if not status.downloadUrl:
        raise ValueError("更新配置缺少 downloadUrl")
    webbrowser.open(status.downloadUrl)
    update_manager.set_runtime("opened", 0)
    if tray is not None:
        tray.notify(
            f"已打开版本 {status.latestVersion} 下载页面，请在浏览器中完成下载和替换",
            "CoreInsight Local Toolkit")


def _native_confirm(message: str, title: str = "CoreInsight Local Toolkit") -> bool:
    try:
        return ctypes.windll.user32.MessageBoxW(None, message, title, 0x24) == 6
    except Exception:
        logger.warning("desktop confirmation unavailable: %s", message)
        return False


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
        if isinstance(health, dict) and isinstance(health.get('data'), dict):
            health = health['data']
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
    instance = _SingleInstanceMutex()
    try:
        acquired = instance.acquire()
    except Exception as exc:
        logger.exception("single-instance mutex creation failed")
        _native_notice(f"无法建立单实例锁，Toolkit 未启动：\n{exc}")
        return
    if not acquired:
        # The primary process may still be starting its HTTP listener.
        for _attempt in range(40):
            if _activate_existing(settings.port):
                logger.info("existing toolkit instance activated")
                return
            time.sleep(0.25)
        logger.info("another toolkit instance is already running")
        _native_notice("CoreInsight Local Toolkit 已在运行。")
        return
    try:
        _run_desktop_primary(settings)
    finally:
        instance.close()


def _run_desktop_primary(settings: Settings) -> None:
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
    update_manager = UpdateManager(settings)
    application = create_app(settings, update_manager)

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

    try:
        _ensure_default_autostart()
    except Exception:
        logger.exception("default autostart registration failed")

    environments = EnvironmentManager(settings.data_dir)
    source_image = Image.open(asset_path("icon.png")).convert("RGBA")

    def open_url(url: str) -> None:
        webbrowser.open(url)

    def environment_url(url: str) -> str:
        return environments.resolve_url(url)

    def open_portal() -> None:
        open_url(environment_url(settings.portal_url))

    def open_experience_create() -> None:
        open_url(environment_url(settings.experience_create_url))

    def show_about(*_args) -> None:
        _native_notice(
            f"CoreInsight Local Toolkit\n版本：{__version__}\n"
            f"环境：{environments.label(settings.portal_url)}\n"
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

    def toggle_autostart(*_args) -> None:
        enabled = not bool(_read_autostart_command())
        try:
            _set_autostart(enabled)
            tray.update_menu()
            tray.notify(
                "已开启开机自启" if enabled else "已关闭开机自启",
                "CoreInsight Local Toolkit")
        except Exception as exc:
            logger.exception("toggle autostart failed enabled=%s", enabled)
            _native_notice(f"修改开机自启失败：\n{exc}")

    exiting = threading.Event()

    def switch_environment(environment: str) -> None:
        previous = environments.current(settings.portal_url)
        environments.set(environment)
        if previous == environment:
            return
        label = environments.label(settings.portal_url)
        logger.info('desktop environment changed environment=%s', environment)
        try:
            tray.update_menu()
            tray.notify(f'已切换到{label}', 'CoreInsight Local Toolkit')
        except Exception:
            logger.debug('tray environment refresh unavailable', exc_info=True)

    def check_update(manual: bool = False) -> None:
        def worker() -> None:
            try:
                status = update_manager.check()
                if not status.configured:
                    message = "尚未配置更新信息"
                elif status.forceUpdate:
                    message = f"当前版本已停用，必须更新到 {status.latestVersion}"
                    tray.notify(message, "CoreInsight Local Toolkit")
                    open_update_page(status, update_manager, tray)
                    return
                elif status.updateAvailable:
                    message = f"发现新版本 {status.latestVersion}"
                    if manual and _native_confirm(
                            f"发现新版本 {status.latestVersion}，是否立即下载并安装？\n\n"
                            + "\n".join(status.releaseNotes)):
                        open_update_page(status, update_manager, tray)
                        return
                else:
                    message = f"当前已是最新版本 {status.currentVersion}"
                tray.notify(message, "CoreInsight Local Toolkit")
            except Exception as exc:
                logger.exception("update check failed")
                tray.notify(f"版本检查失败：{exc}", "CoreInsight Local Toolkit")
        threading.Thread(target=worker, name="update-check", daemon=True).start()

    try:
        floating = FloatingWindow(source_image, {
            "portal": open_portal,
            "experience_create": open_experience_create,
            "environment_current": lambda: environments.current(settings.portal_url),
            "environment_production": lambda: switch_environment(PRODUCTION),
            "environment_testing": lambda: switch_environment(TESTING),
            "logs": open_logs,
            "autostart_enabled": lambda: bool(_read_autostart_command()),
            "autostart_toggle": toggle_autostart,
            "update": lambda: check_update(True),
            "about": show_about,
        })
    except Exception:
        server.should_exit = True
        server_thread.join(timeout=10)
        raise
    update_manager.set_installer(
        lambda status: open_update_page(status, update_manager, tray))

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
            pystray.MenuItem("云见主页", lambda *_: open_portal()),
            pystray.MenuItem("经验提取", lambda *_: open_experience_create()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "生产环境", lambda *_: switch_environment(PRODUCTION),
                checked=lambda _item: environments.current(settings.portal_url) == PRODUCTION,
                radio=True),
            pystray.MenuItem(
                "测试环境", lambda *_: switch_environment(TESTING),
                checked=lambda _item: environments.current(settings.portal_url) == TESTING,
                radio=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开日志目录", open_logs),
            pystray.MenuItem(
                "开机自启", toggle_autostart,
                checked=lambda _item: bool(_read_autostart_command())),
            pystray.MenuItem("检查更新", lambda *_: check_update(True)),
            pystray.MenuItem("关于", lambda *_: floating.post(WM_APP_ABOUT)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示悬浮图标", lambda *_: floating.post(WM_APP_SHOW), default=True),
            pystray.MenuItem("退出", lambda *_: floating.post(WM_APP_EXIT)),
        ),
    )
    tray_thread = threading.Thread(target=tray.run, name="coreinsight-tray", daemon=True)
    tray_thread.start()
    if settings.welcome_enabled:
        welcome_url = f"http://127.0.0.1:{settings.port}/welcome/"
        threading.Timer(0.5, lambda: open_url(welcome_url)).start()
    threading.Timer(2.0, lambda: check_update(False)).start()
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
