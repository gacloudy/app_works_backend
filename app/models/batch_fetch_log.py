from datetime import datetime
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class BatchFetchLog(Base):
    __tablename__ = "batch_fetch_log"
    __table_args__ = {"schema": "trader_schema"}

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id:     Mapped[str]      = mapped_column(String(20), nullable=False)  # "YYYYMMDD_HHMMSS"
    code:       Mapped[str]      = mapped_column(String(10), nullable=False)
    status:     Mapped[str]      = mapped_column(String(10), nullable=False)  # "skip" | "error"
    reason:     Mapped[str]      = mapped_column(String(100), nullable=False)
    source:     Mapped[str|None] = mapped_column(String(20), nullable=True)   # "nomura" | "yahoo" | None
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
