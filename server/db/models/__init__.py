from datetime import datetime, timezone

from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
