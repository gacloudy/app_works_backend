"""
docs/kb/knowledge_base.md を読み込み、チャンクに分割してVoyage AIで埋め込みを作成し、
kb_chunk テーブルに upsert する一回限りの実行スクリプト。

ナレッジベースの内容を編集したら、その都度このスクリプトを再実行すること。
本文が変わっていないチャンクは content_hash が一致するため埋め込みをスキップし、
変更があったチャンクのみ再埋め込みする（冪等）。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python scripts\\ingest_kb.py
"""

import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal
from app.models.kb_chunk import KbChunk
from app.rag.chunking import content_hash, parse_kb_markdown
from app.rag.embeddings import EMBED_MODEL, embed_documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

KB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "kb", "knowledge_base.md")


def main() -> None:
    log.info("=== ナレッジベース取り込みバッチ 開始 ===")
    with open(KB_PATH, encoding="utf-8") as f:
        text = f.read()
    sources = parse_kb_markdown(text)
    log.info("ナレッジベースのチャンク数: %d 件", len(sources))

    with SessionLocal() as db:
        existing = {row.chunk_key: row for row in db.query(KbChunk).all()}
        to_embed = [
            s for s in sources
            if s.chunk_key not in existing or existing[s.chunk_key].content_hash != content_hash(s.content)
        ]
        log.info("埋め込み対象（新規・変更分）: %d / %d 件", len(to_embed), len(sources))

        if to_embed:
            vectors = embed_documents([s.content for s in to_embed])
            now = datetime.now()
            records = [
                {
                    "chunk_key": s.chunk_key,
                    "title": s.title,
                    "category": s.category,
                    "content": s.content,
                    "content_hash": content_hash(s.content),
                    "embedding": vec,
                    "embedding_model": EMBED_MODEL,
                    "created_at": now,
                    "updated_at": now,
                }
                for s, vec in zip(to_embed, vectors)
            ]
            stmt = pg_insert(KbChunk).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["chunk_key"],
                set_={
                    "title": stmt.excluded.title,
                    "category": stmt.excluded.category,
                    "content": stmt.excluded.content,
                    "content_hash": stmt.excluded.content_hash,
                    "embedding": stmt.excluded.embedding,
                    "embedding_model": stmt.excluded.embedding_model,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            db.execute(stmt)
            db.commit()

    log.info("完了: %d 件を upsert", len(to_embed))
    log.info("=== ナレッジベース取り込みバッチ 終了 ===")


if __name__ == "__main__":
    main()
