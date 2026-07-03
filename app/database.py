import os
import logging
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

log = logging.getLogger(__name__)


def _build_engine():
    if os.environ.get("GCP_PROJECT_ID"):
        from app.gcp_secrets import get_secret
        from google.cloud.sql.connector import Connector
        import pg8000

        log.info("Cloud SQL Connector で接続します")

        db_url = get_secret("DATABASE_URL")
        instance_name = get_secret("CLOUD_SQL_INSTANCE")
        parsed = urlparse(db_url)
        connector = Connector()

        def getconn():
            return connector.connect(
                instance_name,
                "pg8000",
                user=parsed.username,
                password=parsed.password,
                db=parsed.path.lstrip("/"),
            )

        return create_engine(
            "postgresql+pg8000://",
            creator=getconn,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=1800,
        )

    log.info("DATABASE_URL を .env から取得します")
    db_url = os.environ["DATABASE_URL"]
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
