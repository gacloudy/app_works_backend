from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel


class StockPriceBase(BaseModel):
    code: str
    trade_date: date
    open_price:    Decimal | None = None
    high_price:    Decimal | None = None
    low_price:     Decimal | None = None
    prev_close:    Decimal | None = None
    volume:        int | None = None
    current_price: Decimal | None = None
    source:        str | None = None


class StockPriceResponse(StockPriceBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
