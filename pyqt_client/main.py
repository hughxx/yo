"""pywebview desktop entry point (WebView2 on Windows)."""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

import webview

from version import APP_VERSION
from webview_api import AppApi
from desktop_host import DesktopHost
from log_config import configure_logging


def resource_path(*parts: str) -> Path:
    """Resolve bundled resources in both source and PyInstaller onefile modes."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def _exception_hook(exc_type, exc_value, exc_tb):
    logging.getLogger("app").critical(
        "主线程未捕获异常", exc_info=(exc_type, exc_value, exc_tb)
    )
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _single_instance() -> object | None:
    if os.name != "nt":
        return None
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\CoreMinerApp")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, "程序已经在运行，请勿重复启动。", "已在运行", 0x30)
        raise SystemExit(0)
    return mutex


def main() -> None:
    configure_logging()
    # Keep the mutex alive for the whole process.
    mutex = _single_instance()
    sys.excepthook = _exception_hook
    api = AppApi()
    window = webview.create_window(
        f"CoreMiner v{APP_VERSION}",
        resource_path("web", "index.html").as_uri(),
        js_api=api,
        width=1320,
        height=840,
        min_size=(1080, 640),
        background_color="#f7f8fa",
        confirm_close=False,
    )
    api.bind_window(window)
    host = DesktopHost(window, api, resource_path("assets", "icon.ico"))
    api.bind_host(host)
    window.events.loaded += host.start
    window.events.closing += host.on_closing
    window.events.closed += host.shutdown
    webview.start(gui="edgechromium", debug=not getattr(sys, "frozen", False))
    logging.getLogger("app").info("程序退出")
    _ = mutex


if __name__ == "__main__":
    main()
