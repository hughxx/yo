"""pywebview desktop entry point (WebView2 on Windows)."""
from __future__ import annotations

import ctypes
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

import webview

from version import APP_VERSION
from webview_api import AppApi


def resource_path(*parts: str) -> Path:
    """Resolve bundled resources in both source and PyInstaller onefile modes."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def writable_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


def _exception_hook(exc_type, exc_value, exc_tb):
    message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    with (writable_dir() / "error.log").open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===\n{message}")
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _single_instance() -> object | None:
    if os.name != "nt":
        return None
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\FuyaoCollectionApp")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, "程序已经在运行，请勿重复启动。", "已在运行", 0x30)
        raise SystemExit(0)
    return mutex


def main() -> None:
    # Keep the mutex alive for the whole process.
    mutex = _single_instance()
    sys.excepthook = _exception_hook
    api = AppApi()
    window = webview.create_window(
        f"问题定位助手 v{APP_VERSION}",
        resource_path("web", "index.html").as_uri(),
        js_api=api,
        width=1320,
        height=840,
        min_size=(1080, 640),
        background_color="#f7f8fa",
        confirm_close=True,
    )
    api.bind_window(window)
    window.events.closed += api.shutdown
    webview.start(gui="edgechromium", debug=not getattr(sys, "frozen", False))
    _ = mutex


if __name__ == "__main__":
    main()
