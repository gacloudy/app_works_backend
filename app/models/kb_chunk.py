from datetime import datetime
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class KbChunk(Base):
    __tablename__ = "kb_chunk"
    __table_args__ = {"schema": "trader_schema"}

    id:              Mapped[int]        = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_key:       Mapped[str]        = mapped_column(String(100), unique=True, nullable=False)
    title:           Mapped[str]        = mapped_column(String(200), nullable=False)
    category:        Mapped[str]        = mapped_column(String(50), nullable=False)
    content:         Mapped[str]        = mapped_column(Text, nullable=False)
    content_hash:    Mapped[str]        = mapped_column(String(64), nullable=False)
    embedding:       Mapped[list[float]] = mapped_column(ARRAY(Float), nullable=False)
    embedding_model: Mapped[str]        = mapped_column(String(50), nullable=False)
    created_at:      Mapped[datetime]   = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at:      Mapped[datetime]   = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )
