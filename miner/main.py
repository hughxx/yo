from __future__ import annotations
import ctypes
import logging
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
    from . import config
except ImportError:  # PyInstaller entry point is a file, not a package module.
    from miner.bridge import MinerApi
    from miner import config


def main():
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(config.LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    logging.info("Miner starting frozen=%s exe=%s", getattr(sys, "frozen", False), sys.executable)
    api = MinerApi()
    # In a PyInstaller one-file build, bundled data is unpacked under
    # sys._MEIPASS rather than next to the executable.
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    web_root = root / "miner" / "web"
    if not (web_root / "index.html").exists():
        web_root = root / "web"
    logging.info("Miner web root=%s exists=%s", web_root, (web_root / "index.html").exists())
    page = _inline_web_assets(web_root)
    window = webview.create_window("邮件聊天记录提取工具", html=page, js_api=api, width=1180, height=760, min_size=(960, 620), background_color="#f7f8fb")
    api.bind_window(window)
    window.events.loaded += lambda: logging.info("Miner web page loaded")
    window.events.closed += lambda: logging.info("Miner web window closed")
    threading.Timer(5.0, lambda: _probe_webview(window)).start()
    tray = _start_tray(api, window)
    try:
        webview.start(gui="edgechromium", debug=not getattr(sys, "frozen", False))
    except Exception:
        logging.exception("Miner webview failed to start")
        raise
    logging.info("Miner webview stopped")
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

    icon = pystray.Icon("Miner", _tray_image(), "邮件聊天记录提取工具", pystray.Menu(
        TrayItem("打开邮件聊天记录提取工具", lambda icon, item: None, default=True),
        TrayItem("检查更新", check),
        TrayItem("退出", quit_app),
    ))
    threading.Thread(target=icon.run, daemon=True).start()
    if config.FORCE_UPDATE and config.DOWNLOAD_URL:
        threading.Timer(2.0, lambda: webbrowser.open(config.DOWNLOAD_URL)).start()
    return icon


def _inline_web_assets(web_root: Path) -> str:
    """将静态资源内嵌后交给 pywebview，避免 file:// 页面影响 API 注入。"""
    html = (web_root / "index.html").read_text(encoding="utf-8")
    css = (web_root / "styles.css").read_text(encoding="utf-8")
    js = (web_root / "app.js").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="app.js"></script>', f"<script>\n{js}\n</script>")
    return html


def _probe_webview(window) -> None:
    try:
        value = window.evaluate_js("JSON.stringify({pywebview:typeof window.pywebview,api:typeof (window.pywebview&&window.pywebview.api),folders:typeof (window.pywebview&&window.pywebview.api&&window.pywebview.api.list_folders)})")
        logging.info("Miner webview API probe=%s", value)
    except Exception:
        logging.exception("Miner webview API probe failed")


if __name__ == "__main__":
    main()
