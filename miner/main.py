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
    root = Path(__file__).resolve().parent
    window = webview.create_window("CoreInsight Miner", (root / "web" / "index.html").as_uri(), js_api=api, width=1180, height=760, min_size=(960, 620), background_color="#f7f8fb")
    api.bind_window(window)
    webview.start(gui="edgechromium", debug=not getattr(sys, "frozen", False))


if __name__ == "__main__":
    main()
