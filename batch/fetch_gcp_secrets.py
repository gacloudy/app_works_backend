"""
GCP Secret Manager からシークレットを取得して動作確認するバッチ。

取得したシークレット値で DB 接続テストも行う。

実行方法:
    cd backend
    .venv\\Scripts\\python -m batch.fetch_gcp_secrets

必須環境変数:
    GCP_PROJECT_ID                  : GCP プロジェクト ID
    GOOGLE_APPLICATION_CREDENTIALS  : サービスアカウントキー JSON のパス（ローカル実行時）

GCP Secret Manager に登録が必要なシークレット:
    DATABASE_URL  : postgresql://user:pass@host:5432/dbname
"""

import sys
import os
import logging
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")

SECRET_NAMES = [
    "DATABASE_URL",
]


def test_db_connection(database_url: str) -> bool:
    """取得した DATABASE_URL で DB 接続を確認する。"""
    url = database_url.replace("postgresql://", "postgresql+psycopg2://")
    if "?schema=" in url:
        url = url.split("?schema=")[0]
    try:
        engine = create_engine(url, echo=False)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.error("DB 接続失敗: %s", exc)
        return False


def main() -> None:
    if not PROJECT_ID:
        log.error("環境変数 GCP_PROJECT_ID が設定されていません")
        sys.exit(1)

    log.info("=== GCP Secret Manager 取得バッチ 開始 ===")
    log.info("プロジェクト: %s", PROJECT_ID)

    from app.gcp_secrets import get_secret

    secrets: dict[str, str] = {}

    for secret_name in SECRET_NAMES:
        try:
            value = get_secret(secret_name)
            secrets[secret_name] = value
            masked = value[:10] + "..." if len(value) > 10 else "***"
            log.info("[%s] 取得成功: %s", secret_name, masked)
        except Exception as exc:
            log.error("[%s] 取得失敗: %s", secret_name, exc)

    if "DATABASE_URL" in secrets:
        log.info("DB 接続テスト中...")
        ok = test_db_connection(secrets["DATABASE_URL"])
        if ok:
            log.info("DB 接続テスト: 成功")
        else:
            log.error("DB 接続テスト: 失敗")

    log.info("=== GCP Secret Manager 取得バッチ 終了 ===")


if __name__ == "__main__":
    main()
