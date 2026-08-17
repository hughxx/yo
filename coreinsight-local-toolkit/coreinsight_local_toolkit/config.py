from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ORIGINS = (
    "https://coreinsight-beta.rnd.huawei.com",
    "https://coreinsight.rnd.huawei.com",
    "http://localhost.huawei.com:8080",
    "https://localhost.huawei.com:8080",
)


def _data_dir() -> Path:
    configured = (
        os.getenv("COREINSIGHT_TOOLKIT_DATA_DIR", "").strip()
        or os.getenv("COREINSIGHT_AGENT_DATA_DIR", "").strip()
    )
    if configured:
        return Path(configured).expanduser()
    return Path("D:/CoreInsight/LocalToolkit")


def _origins() -> tuple[str, ...]:
    raw = os.getenv("COREINSIGHT_ALLOWED_ORIGINS", "").strip()
    values = [*DEFAULT_ORIGINS, *(raw.split(",") if raw else [])]
    return tuple(dict.fromkeys(
        value.strip().rstrip("/") for value in values if value.strip()))


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 17831
    data_dir: Path = _data_dir()
    allowed_origins: tuple[str, ...] = _origins()
    welink_cli: str = os.getenv("COREINSIGHT_WELINK_CLI", "welink-cli").strip() or "welink-cli"
    upload_by: str = os.getenv("COREINSIGHT_UPLOAD_BY", "").strip()
    hermes_url: str = os.getenv(
        "COREINSIGHT_HERMES_URL", "http://7.183.107.92:31454"
    ).strip().rstrip("/")
    hermes_api_key: str = os.getenv(
        "COREINSIGHT_HERMES_API_KEY", "hermes-internal-dev-key"
    ).strip()
    workspace_file_server_url: str = os.getenv(
        "COREINSIGHT_WORKSPACE_FILE_SERVER_URL", "http://7.183.107.92:30864"
    ).strip().rstrip("/")
    experience_engine_url: str = os.getenv(
        "COREINSIGHT_EXPERIENCE_ENGINE_URL", "https://fuyao.rnd.huawei.com"
    ).strip().rstrip("/")
    draft_api_url: str = os.getenv(
        'COREINSIGHT_DRAFT_API_URL', 'https://coreinsight.rnd.huawei.com/chat'
    ).strip().rstrip('/')
    ocr_url: str = os.getenv(
        "COREINSIGHT_OCR_URL", "http://10.90.113.228:5678/ocr"
    ).strip()
    image_file_server_url: str = os.getenv(
        "COREINSIGHT_FILE_SERVER_URL", "http://7.224.100.105:32169"
    ).strip().rstrip("/")
    rag_pic_public_base: str = os.getenv(
        "COREINSIGHT_RAG_PIC_PUBLIC_BASE", "https://fuyao-data-server.rnd.huawei.com"
    ).strip().rstrip("/")
    clouddrive_account: str = os.getenv("COREINSIGHT_CLOUDDRIVE_ACCOUNT", "").strip()
    clouddrive_password: str = os.getenv("COREINSIGHT_CLOUDDRIVE_PASSWORD", "").strip()
    hermes_timeout_seconds: int = 1800
    portal_url: str = os.getenv(
        "COREINSIGHT_PORTAL_URL", "https://coreinsight.rnd.huawei.com"
    ).strip()
    email_url: str = os.getenv("COREINSIGHT_EMAIL_URL", "").strip()
    chat_url: str = os.getenv("COREINSIGHT_CHAT_URL", "").strip()
    update_config_url: str = os.getenv(
        "COREINSIGHT_UPDATE_CONFIG_URL",
        "https://fuyao.rnd.huawei.com/dataengineering/rag-knowledge-config/selectConfigByKey",
    ).strip()
    update_config_key: str = os.getenv(
        "COREINSIGHT_UPDATE_CONFIG_KEY", "coreinsight_local_toolkit_release"
    ).strip()
    update_enabled: bool = os.getenv(
        "COREINSIGHT_UPDATE_ENABLED", "1"
    ).strip().lower() not in {"0", "false", "no"}
    tray_enabled: bool = os.getenv(
        "COREINSIGHT_TRAY_ENABLED", "1"
    ).strip().lower() not in {"0", "false", "no"}


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
