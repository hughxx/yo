"""Bounded file logging for the desktop host and background workers."""
from __future__ import annotations

import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_FILE_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
RETENTION_DAYS = 14
TOTAL_LIMIT_BYTES = 30 * 1024 * 1024


def program_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


def _log_dir() -> Path:
    preferred = program_dir() / "log"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        from paths import app_data_dir
        fallback = app_data_dir() / "log"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _cleanup(folder: Path) -> None:
    now = time.time()
    files = sorted(
        (path for path in folder.glob("*.log*") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    for path in list(files):
        if now - path.stat().st_mtime > RETENTION_DAYS * 86400:
            try:
                path.unlink()
                files.remove(path)
            except OSError:
                pass
    total = sum(path.stat().st_size for path in files if path.exists())
    for path in files:
        if total <= TOTAL_LIMIT_BYTES:
            break
        if path.name == "app.log":
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            total -= size
        except OSError:
            pass


def configure_logging() -> Path:
    folder = _log_dir()
    _cleanup(folder)
    handler = RotatingFileHandler(
        folder / "app.log",
        maxBytes=MAX_FILE_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)s] [%(threadName)s] %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.captureWarnings(True)

    def thread_exception(args):
        logging.getLogger("thread").critical(
            "后台线程未捕获异常：%s", args.thread.name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = thread_exception
    logging.getLogger("app").info("日志系统启动；目录=%s", folder)
    return folder
