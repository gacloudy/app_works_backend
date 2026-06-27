from datetime import datetime
from pydantic import BaseModel


class StockMasterBase(BaseModel):
    code: str
    name: str
    industry: str
    market: str | None = None


class StockMasterCreate(StockMasterBase):
    pass


class StockMasterUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    market: str | None = None


class StockMasterResponse(StockMasterBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
