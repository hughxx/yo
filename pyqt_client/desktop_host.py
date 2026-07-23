"""Native window lifecycle and Windows system tray integration."""
from __future__ import annotations

import threading
from pathlib import Path

from PIL import Image
import pystray


class DesktopHost:
    def __init__(self, window, api, icon_path: Path):
        self.window = window
        self.api = api
        self.icon_path = icon_path
        self._tray = None
        self._quitting = False
        self._notified = False
        self._lock = threading.Lock()

    def start(self):
        if self._tray:
            return
        image = Image.open(self.icon_path)
        self._tray = pystray.Icon(
            "problem-locating-assistant",
            image,
            "CoreMiner",
            menu=pystray.Menu(
                pystray.MenuItem("显示", self._show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit_from_tray),
            ),
        )
        self._tray.run_detached()

    def on_closing(self):
        if self._quitting:
            return True
        self.window.hide()
        if self._tray and not self._notified:
            self._notified = True
            try:
                self._tray.notify("程序已缩小到系统托盘，后台任务继续运行。", "CoreMiner")
            except Exception:
                pass
        return False  # cancel native close; the window is hidden instead

    def _show(self, *_args):
        self.window.show()
        self.window.restore()

    def _quit_from_tray(self, *_args):
        self.quit()

    def quit(self):
        with self._lock:
            if self._quitting:
                return
            self._quitting = True
        self.api.shutdown()
        if self._tray:
            self._tray.stop()
        self.window.destroy()

    def shutdown(self, *_args):
        if not self._quitting:
            self.api.shutdown()
        if self._tray:
            self._tray.stop()
