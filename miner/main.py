from __future__ import annotations
import ctypes
import sys
from pathlib import Path

import webview

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
    webview.start(gui="edgechromium", debug=not getattr(sys, "frozen", False))


if __name__ == "__main__":
    main()
