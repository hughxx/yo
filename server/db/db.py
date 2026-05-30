from urllib.parse import quote_plus

import pymysql
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.utils.settings import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from server.db.models import Base
import server.db.models.email        # noqa: F401 — registers Collection/Email/EmailNamespace/EmailRule
import server.db.models.welink       # noqa: F401 — registers WelinkChatlog
import server.db.models.process_log  # noqa: F401 — registers ProcessLog

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

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


def init_db():
    try:
        conn = pymysql.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD
        )
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: could not ensure database: {e}")
    Base.metadata.create_all(bind=engine)
