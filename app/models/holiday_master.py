from datetime import date, datetime
from sqlalchemy import Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class HolidayMaster(Base):
    __tablename__ = "holiday_master"
    __table_args__ = {"schema": "trader_schema"}

    date:       Mapped[date]     = mapped_column(Date, primary_key=True, nullable=False)
    name:       Mapped[str]      = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
