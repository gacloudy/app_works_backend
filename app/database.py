import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

log = logging.getLogger(__name__)


def _resolve_database_url() -> str:
    if os.environ.get("GCP_PROJECT_ID"):
        from app.gcp_secrets import get_secret
        log.info("DATABASE_URL を Secret Manager から取得します")
        return get_secret("DATABASE_URL")
    log.info("DATABASE_URL を .env から取得します")
    return os.environ["DATABASE_URL"]


_url = _resolve_database_url()
if "?schema=" in _url:
    _url = _url.split("?schema=")[0]
DATABASE_URL = _url.replace("postgresql://", "postgresql+psycopg2://")

engine = create_engine(DATABASE_URL, echo=False)

# 接続時にsearch_pathをtrader_schemaに設定する
@event.listens_for(engine, "connect")
def set_search_path(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("SET search_path TO trader_schema")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
