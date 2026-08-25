from __future__ import annotations
import ctypes
import sys
import threading
import webbrowser
from pathlib import Path

import webview
import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem as TrayItem

try:
    from .bridge import MinerApi
except ImportError:  # PyInstaller entry point is a file, not a package module.
    from miner.bridge import MinerApi


def main():
    api = MinerApi()
    # In a PyInstaller one-file build, bundled data is unpacked under
    # sys._MEIPASS rather than next to the executable.
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    web_root = root / "miner" / "web"
    if not (web_root / "index.html").exists():
        web_root = root / "web"
    window = webview.create_window("CoreInsight Miner", (web_root / "index.html").as_uri(), js_api=api, width=1180, height=760, min_size=(960, 620), background_color="#f7f8fb")
    api.bind_window(window)
    tray = _start_tray(api, window)
    webview.start(gui="edgechromium", debug=not getattr(sys, "frozen", False))
    tray.stop()


def _tray_image():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stops = [(226, 75, 74), (239, 159, 39), (99, 153, 34), (24, 95, 165)]
    for y in range(64):
        for x in range(64):
            dx, dy = x - 32, y - 32
            if dx * dx + dy * dy <= 28 * 28:
                t = max(0.0, min(1.0, (x + y) / 126)) * (len(stops) - 1)
                i, f = min(int(t), len(stops) - 2), t % 1
                a, b = stops[i], stops[i + 1]
                draw.point((x, y), fill=tuple(int(a[j] * (1 - f) + b[j] * f) for j in range(3)) + (255,))
    return image


def _start_tray(api, window):
    def check(icon, item):
        result = api.check_update()
        if result.get("downloadUrl") and (result.get("forceUpdate") or result.get("latestVersion") != result.get("currentVersion")):
            webbrowser.open(result["downloadUrl"])

    def quit_app(icon, item):
        icon.stop()
        try:
            window.destroy()
        except Exception:
            pass

    icon = pystray.Icon("CoreInsight Miner", _tray_image(), "CoreInsight Miner", pystray.Menu(
        TrayItem("打开 Miner", lambda icon, item: None, default=True),
        TrayItem("检查更新", check),
        TrayItem("退出", quit_app),
    ))
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


if __name__ == "__main__":
    main()
