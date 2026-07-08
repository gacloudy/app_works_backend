"""
Voyage AI を使った埋め込み（embedding）生成の薄いラッパー。

Voyage は「ドキュメント側」と「クエリ側」で埋め込みの最適化が異なる
非対称embedding（asymmetric embedding）をサポートしており、`input_type` で
"document"（格納するチャンク側）と "query"（検索する質問側）を使い分ける。
"""

import os

import voyageai

EMBED_MODEL = "voyage-4-lite"

_client: voyageai.Client | None = None


def _get_client() -> voyageai.Client:
    global _client
    if _client is None:
        if not os.environ.get("VOYAGE_API_KEY"):
            raise RuntimeError("VOYAGE_API_KEY が設定されていません")
        _client = voyageai.Client()
    return _client


def embed_documents(texts: list[str]) -> list[list[float]]:
    """ナレッジベースのチャンク本文を埋め込む（格納用）。"""
    result = _get_client().embed(texts, model=EMBED_MODEL, input_type="document")
    return result.embeddings


def embed_query(text: str) -> list[float]:
    """ユーザーの質問文を埋め込む（検索用）。"""
    result = _get_client().embed([text], model=EMBED_MODEL, input_type="query")
    return result.embeddings[0]
