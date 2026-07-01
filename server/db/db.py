from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.utils import settings as _st
from server.db.models import Base
import server.db.models.email        # noqa: F401 — registers Collection/Email/EmailNamespace/EmailRule
import server.db.models.welink       # noqa: F401 — registers WelinkChatlog
import server.db.models.process_log  # noqa: F401 — registers ProcessLog

# 方言：postgresql（= GaussDB / openGauss，走 PG 协议）| mysql。默认 postgresql。
DB_DIALECT = getattr(_st, "DB_DIALECT", "postgresql").lower()
# PG 驱动名（GaussDB 通常用华为编译版 psycopg2，仍以 psycopg2 注册）
DB_DRIVER = getattr(_st, "DB_DRIVER", "psycopg2")
# 建库时连接的维护库（PG/GaussDB 不能在目标库里 CREATE DATABASE 自己）
DB_MAINTENANCE = getattr(_st, "DB_MAINTENANCE", "postgres")


def _build_url(dbname: str) -> str:
    user = quote_plus(_st.DB_USER)
    pwd  = quote_plus(_st.DB_PASSWORD)
    host, port = _st.DB_HOST, _st.DB_PORT
    if DB_DIALECT in ("mysql", "mariadb"):
        return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{dbname}?charset=utf8mb4"
    # postgresql / gaussdb / opengauss
    return f"postgresql+{DB_DRIVER}://{user}:{pwd}@{host}:{port}/{dbname}?client_encoding=utf8"


def _patch_gaussdb_version() -> None:
    """SQLAlchemy 的 PG 方言用正则从 version() 抠 PostgreSQL 版本号，
    而 GaussDB 返回 'gaussdb (GaussDB Kernel 505.2.1 ...)' 匹配不上会抛 AssertionError，
    导致每条连接初始化即失败。GaussDB/openGauss 内核基于 PG 9.2.4，解析失败时回退到该版本。"""
    from sqlalchemy.dialects.postgresql.base import PGDialect

    _orig = PGDialect._get_server_version_info

    def _safe(self, connection):
        try:
            return _orig(self, connection)
        except AssertionError:
            return (9, 2, 4)

    PGDialect._get_server_version_info = _safe


DATABASE_URL = _build_url(_st.DB_NAME)

if DB_DIALECT not in ("mysql", "mariadb"):
    _patch_gaussdb_version()

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_database_mysql() -> None:
    import pymysql
    conn = pymysql.connect(
        host=_st.DB_HOST, port=_st.DB_PORT, user=_st.DB_USER, password=_st.DB_PASSWORD
    )
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{_st.DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.commit()
    conn.close()


def _ensure_database_postgres() -> None:
    """PG/GaussDB：连维护库，库不存在才 CREATE DATABASE（CREATE DATABASE 不能在事务里跑）。"""
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(
        host=_st.DB_HOST, port=_st.DB_PORT, user=_st.DB_USER,
        password=_st.DB_PASSWORD, dbname=DB_MAINTENANCE,
    )
    conn.autocommit = True   # CREATE DATABASE 不能在事务块里执行
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_st.DB_NAME,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(_st.DB_NAME)))
    finally:
        conn.close()


def init_db():
    """默认不自动建库建表（手动执行 server/db/schema_gaussdb.md 里的 SQL）。

    需要自动建时在 settings 里设 DB_AUTO_INIT = True：PG/GaussDB 会先确保库存在，
    再 create_all 建表（MySQL 同理）。
    """
    if not getattr(_st, "DB_AUTO_INIT", False):
        return
    try:
        if DB_DIALECT in ("mysql", "mariadb"):
            _ensure_database_mysql()
        else:
            _ensure_database_postgres()
    except Exception as e:
        print(f"Warning: could not ensure database: {e}")
    Base.metadata.create_all(bind=engine)
