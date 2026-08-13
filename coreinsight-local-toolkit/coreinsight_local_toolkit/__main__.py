import logging
import os
import shutil
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from .app import create_app
from .config import load_settings


def configure_logging(data_dir: Path) -> Path:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "toolkit.log"
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return log_path


def cleanup_stale_runtime(data_dir: Path, max_age_seconds: int = 86_400) -> int:
    runtime_dir = data_dir / "runtime"
    if not runtime_dir.is_dir():
        return 0
    active = Path(getattr(sys, "_MEIPASS", "")).resolve() \
        if getattr(sys, "_MEIPASS", "") else None
    cutoff = time.time() - max_age_seconds
    removed = 0
    for candidate in runtime_dir.glob("_MEI*"):
        try:
            if active and candidate.resolve() == active:
                continue
            if candidate.is_dir() and candidate.stat().st_mtime < cutoff:
                shutil.rmtree(candidate)
                removed += 1
        except OSError:
            logging.getLogger(__name__).warning(
                "stale runtime cleanup failed path=%s", candidate, exc_info=True)
    return removed


def main() -> None:
    settings = load_settings()
    log_path = configure_logging(settings.data_dir)
    logging.getLogger(__name__).info("CoreInsight Local Toolkit starting; log=%s", log_path)
    removed = cleanup_stale_runtime(settings.data_dir)
    if removed:
        logging.getLogger(__name__).info("removed stale runtime directories count=%d", removed)
    if os.name == "nt" and settings.tray_enabled:
        try:
            from .desktop import run_desktop
            run_desktop(settings)
            return
        except ImportError:
            logging.getLogger(__name__).warning(
                "desktop dependencies unavailable; running without desktop host", exc_info=True)
        except Exception:
            logging.getLogger(__name__).exception(
                "desktop host startup failed; running without desktop host")
    uvicorn.run(
        create_app(settings), host=settings.host, port=settings.port,
        log_level="info", log_config=None)


if __name__ == "__main__":
    main()
