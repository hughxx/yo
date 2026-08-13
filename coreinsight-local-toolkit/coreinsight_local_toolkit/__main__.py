import logging
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


def main() -> None:
    settings = load_settings()
    log_path = configure_logging(settings.data_dir)
    logging.getLogger(__name__).info("CoreInsight Local Toolkit starting; log=%s", log_path)
    uvicorn.run(
        create_app(settings), host=settings.host, port=settings.port,
        log_level="info", log_config=None)


if __name__ == "__main__":
    main()
