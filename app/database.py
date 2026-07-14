import os
import logging

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

log = logging.getLogger(__name__)


def _get_database_url() -> str:
    if os.environ.get("GCP_PROJECT_ID"):
        from app.gcp_secrets import get_secret

        log.info("Secret Manager から DATABASE_URL を取得します")
        return get_secret("DATABASE_URL")

    log.info("DATABASE_URL を .env から取得します")
    return os.environ["DATABASE_URL"]


def _build_engine():
    db_url = _get_database_url()
    if "?schema=" in db_url:
        db_url = db_url.split("?schema=")[0]
    return create_engine(
        db_url.replace("postgresql://", "postgresql+psycopg2://"),
        echo=False,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


engine = _build_engine()


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
