"""
Markdown形式のナレッジベース文書を、DBに格納するチャンク単位に分割するユーティリティ。

`##` 見出しを1チャンクとして扱い、見出し直後の
`<!-- chunk_key: xxx category: yyy -->` コメントから安定キーとカテゴリを抽出する。
"""

import hashlib
import re
from dataclasses import dataclass

_HEADING_RE = re.compile(
    r"^##\s+(?P<title>.+?)\s*<!--\s*chunk_key:\s*(?P<chunk_key>\S+)\s+category:\s*(?P<category>\S+)\s*-->\s*$",
    re.MULTILINE,
)


@dataclass
class KbChunkSource:
    chunk_key: str
    title: str
    category: str
    content: str


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_kb_markdown(text: str) -> list[KbChunkSource]:
    """`##` 見出しごとにテキストを分割し、チャンクのリストを返す。"""
    matches = list(_HEADING_RE.finditer(text))
    chunks: list[KbChunkSource] = []

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        chunks.append(
            KbChunkSource(
                chunk_key=m.group("chunk_key"),
                title=m.group("title").strip(),
                category=m.group("category").strip(),
                content=f"{m.group('title').strip()}\n{body}",
            )
        )

    return chunks
