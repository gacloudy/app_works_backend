"""
stock_master の上場廃止フラグを stock_price に反映するバッチ。

処理内容:
  - stock_master.isDelisted = TRUE の銘柄コードを取得
  - 該当コードの stock_price レコードを is_delisted = TRUE に一括更新

実行方法:
    cd backend
    .venv\\Scripts\\python -m batch.sync_delisted_prices
"""

import sys
import os
import logging
from datetime import datetime

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.stock_master import StockMaster
from app.models.stock_price import StockPrice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    start_dt = datetime.now()
    log.info("=== 上場廃止フラグ同期バッチ 開始 ===")

    with SessionLocal() as db:
        # 上場廃止銘柄コードを取得
        delisted_codes: list[str] = [
            code for (code,) in
            db.query(StockMaster.code).filter(StockMaster.is_delisted == True).all()  # noqa: E712
        ]
        log.info("上場廃止銘柄数 (stock_master): %d 件", len(delisted_codes))

        if not delisted_codes:
            log.info("上場廃止銘柄がないため処理をスキップします")
        else:
            # stock_price の is_delisted を一括更新
            updated = (
                db.query(StockPrice)
                .filter(StockPrice.code.in_(delisted_codes))
                .filter(StockPrice.is_delisted == False)  # noqa: E712
                .update({"is_delisted": True}, synchronize_session="fetch")
            )
            db.commit()
            log.info("stock_price 更新件数: %d 件", updated)

    elapsed = (datetime.now() - start_dt).total_seconds()
    log.info("完了 (%.1f 秒)", elapsed)
    log.info("=== 上場廃止フラグ同期バッチ 終了 ===")


if __name__ == "__main__":
    main()
