import logging
import traceback

from server.db.db import SessionLocal
from server.db.models.process_log import ProcessLog

logger = logging.getLogger(__name__)


def log_process_error(source: str, ref_key: str, scope: str, exc: BaseException) -> None:
    """记录一条后台处理失败日志，供直接用 SQL 排查。

    source : 'email' / 'welink' / 'welink_daily'
    ref_key: 定位记录的主键（conversation_topic 或 chat_id）
    scope  : 业务上下文（namespace_name 或 group_name）
    exc    : 捕获到的异常对象
    """
    db = SessionLocal()
    try:
        db.add(ProcessLog(
            source       = (source or "")[:20],
            ref_key      = (ref_key or "")[:500],
            scope        = (scope or "")[:200],
            error_type   = type(exc).__name__[:100],
            error_detail = traceback.format_exc()[:65000],
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("failed to write process log")
    finally:
        db.close()
