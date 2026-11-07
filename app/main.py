from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth import verify_token
from app.routers import chat, disclosures, market, picks, signals, stock_master, stock_price, stock_signals

app = FastAPI(
    title="株価分析 API",
    description="日本株価データの管理・分析を行うバックエンドAPI",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # frontend dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stock_master.router, prefix="/api/v1", dependencies=[Depends(verify_token)])
app.include_router(stock_price.router, prefix="/api/v1", dependencies=[Depends(verify_token)])
app.include_router(chat.router, prefix="/api/v1", dependencies=[Depends(verify_token)])
app.include_router(signals.router, prefix="/api/v1", dependencies=[Depends(verify_token)])
app.include_router(market.router, prefix="/api/v1", dependencies=[Depends(verify_token)])
app.include_router(disclosures.router, prefix="/api/v1", dependencies=[Depends(verify_token)])
app.include_router(stock_signals.router, prefix="/api/v1", dependencies=[Depends(verify_token)])
app.include_router(picks.router, prefix="/api/v1", dependencies=[Depends(verify_token)])


@app.get("/health")
def health():
    return {"status": "ok"}
