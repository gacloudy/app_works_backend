"""
ナレッジベースのチャンクに対する検索（retrieval）。

チャンク数が数十件程度と少ないため、専用のベクトルDB（pgvectorなど）は使わず、
DBから全件取得してPython側でコサイン類似度を計算するブルートフォース方式にしている。
チャンクが数百〜数千件規模に増えたら、ベクトルインデックス（pgvector等）への移行を検討する。
"""

import numpy as np
from sqlalchemy.orm import Session

from app.models.kb_chunk import KbChunk
from app.rag.embeddings import embed_query


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def search_kb(db: Session, query: str, top_k: int = 3) -> list[KbChunk]:
    """質問文に近い上位top_k件のナレッジベースチャンクを返す。"""
    rows = db.query(KbChunk).all()
    if not rows:
        return []

    query_vec = np.array(embed_query(query))
    scored = [
        (row, _cosine_similarity(query_vec, np.array(row.embedding)))
        for row in rows
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [row for row, _ in scored[:top_k]]
