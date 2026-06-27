from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class StockMaster(Base):
    __tablename__ = "stock_master"
    __table_args__ = {"schema": "trader_schema"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column("code", String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column("name", String(200), nullable=False)
    industry: Mapped[str] = mapped_column("industry", String(100), nullable=False)
    market: Mapped[str | None] = mapped_column("market", String(50), nullable=True)
    is_delisted: Mapped[bool] = mapped_column("isDelisted", Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
