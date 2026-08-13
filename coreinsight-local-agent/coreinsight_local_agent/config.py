from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ORIGINS = (
    "https://coreinsight-beta.rnd.huawei.com",
    "https://coreinsight.rnd.huawei.com",
)


def _data_dir() -> Path:
    configured = os.getenv("COREINSIGHT_AGENT_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "CoreInsight" / "LocalAgent"


def _origins() -> tuple[str, ...]:
    raw = os.getenv("COREINSIGHT_ALLOWED_ORIGINS", "").strip()
    values = raw.split(",") if raw else DEFAULT_ORIGINS
    return tuple(value.strip().rstrip("/") for value in values if value.strip())


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 17831
    data_dir: Path = _data_dir()
    allowed_origins: tuple[str, ...] = _origins()
    welink_cli: str = os.getenv("COREINSIGHT_WELINK_CLI", "welink-cli").strip() or "welink-cli"
    upload_by: str = os.getenv("COREINSIGHT_UPLOAD_BY", "").strip()
    hermes_url: str = os.getenv(
        "COREINSIGHT_HERMES_URL", "http://7.183.107.92:30864"
    ).strip().rstrip("/")
    hermes_api_key: str = os.getenv(
        "COREINSIGHT_HERMES_API_KEY", "hermes-internal-dev-key"
    ).strip()
    workspace_file_server_url: str = os.getenv(
        "COREINSIGHT_WORKSPACE_FILE_SERVER_URL", "http://7.183.107.92:31454"
    ).strip().rstrip("/")
    experience_engine_url: str = os.getenv("COREINSIGHT_EXPERIENCE_ENGINE_URL", "").strip()
    ocr_url: str = os.getenv("COREINSIGHT_OCR_URL", "").strip()
    clouddrive_account: str = os.getenv("COREINSIGHT_CLOUDDRIVE_ACCOUNT", "").strip()
    clouddrive_password: str = os.getenv("COREINSIGHT_CLOUDDRIVE_PASSWORD", "").strip()
    hermes_timeout_seconds: int = 1800


def load_settings() -> Settings:
    raw_port = os.getenv("COREINSIGHT_AGENT_PORT", "17831")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError("COREINSIGHT_AGENT_PORT 必须是整数") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("COREINSIGHT_AGENT_PORT 必须在 1-65535 之间")
    raw_timeout = os.getenv("COREINSIGHT_HERMES_TIMEOUT_SECONDS", "1800")
    try:
        hermes_timeout = int(raw_timeout)
    except ValueError as exc:
        raise RuntimeError("COREINSIGHT_HERMES_TIMEOUT_SECONDS 必须是整数") from exc
    if hermes_timeout < 30:
        raise RuntimeError("COREINSIGHT_HERMES_TIMEOUT_SECONDS 不能小于 30")
    return Settings(port=port, hermes_timeout_seconds=hermes_timeout)
