from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import stock_master, stock_price

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

app.include_router(stock_master.router, prefix="/api/v1")
app.include_router(stock_price.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
