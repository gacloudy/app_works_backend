from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.stock_master import StockMaster
from app.schemas.stock_master import StockMasterCreate, StockMasterResponse, StockMasterUpdate

router = APIRouter(prefix="/stock-master", tags=["stock-master"])


@router.get("/", response_model=list[StockMasterResponse])
def list_stocks(is_delisted: bool | None = None, db: Session = Depends(get_db)):
    q = db.query(StockMaster).order_by(StockMaster.code)
    if is_delisted is not None:
        q = q.filter(StockMaster.is_delisted == is_delisted)
    return q.all()


@router.get("/{code}", response_model=StockMasterResponse)
def get_stock(code: str, db: Session = Depends(get_db)):
    stock = db.query(StockMaster).filter(StockMaster.code == code).first()
    if not stock:
        raise HTTPException(status_code=404, detail="銘柄が見つかりません")
    return stock


@router.post("/", response_model=StockMasterResponse, status_code=201)
def create_stock(body: StockMasterCreate, db: Session = Depends(get_db)):
    if db.query(StockMaster).filter(StockMaster.code == body.code).first():
        raise HTTPException(status_code=409, detail="証券コードが重複しています")
    stock = StockMaster(**body.model_dump())
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@router.patch("/{code}", response_model=StockMasterResponse)
def update_stock(code: str, body: StockMasterUpdate, db: Session = Depends(get_db)):
    stock = db.query(StockMaster).filter(StockMaster.code == code).first()
    if not stock:
        raise HTTPException(status_code=404, detail="銘柄が見つかりません")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(stock, field, value)
    db.commit()
    db.refresh(stock)
    return stock


@router.delete("/{code}", status_code=204)
def delete_stock(code: str, db: Session = Depends(get_db)):
    stock = db.query(StockMaster).filter(StockMaster.code == code).first()
    if not stock:
        raise HTTPException(status_code=404, detail="銘柄が見つかりません")
    db.delete(stock)
    db.commit()
