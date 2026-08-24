from __future__ import annotations

from datetime import datetime, timezone


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def format_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        try:
            value = value.astimezone()
        except (OSError, ValueError):
            # Windows can reject local-time conversion for dates around the
            # Unix epoch (notably 1970-01-01). Keep the parsed wall-clock value
            # instead of turning a valid `since` into a server error.
            value = value.replace(tzinfo=None)
    return value.strftime(DATETIME_FORMAT)


def normalize_datetime(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return value
    return format_datetime(parse_datetime(str(value)))


def epoch_milliseconds(value: str) -> int:
    parsed = parse_datetime(value).astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return int((parsed - epoch).total_seconds() * 1000)
