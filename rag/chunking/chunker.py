"""
문서를 chunks 테이블에 넣을 단위로 분할.

지금은 단어(공백) 기준 슬라이딩 윈도우로 구현 — 토큰 기준으로 더 정확하게 하고 싶으면
tiktoken 등으로 교체 (embedding 모델이 정해지면 그 모델의 tokenizer에 맞추는 게 정확함).
"""
from __future__ import annotations

DEFAULT_CHUNK_SIZE = 300   # 단어 수 기준
DEFAULT_OVERLAP = 50


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    """
    text를 chunk_size 단어 단위로 자르고, overlap만큼 겹치게 슬라이딩.
    반환된 리스트의 인덱스가 그대로 chunks.chunk_index가 됨.
    """
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    step = max(chunk_size - overlap, 1)
    for start in range(0, len(words), step):
        window = words[start : start + chunk_size]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + chunk_size >= len(words):
            break
    return chunks


def build_chunk_rows(document_id: str, text: str) -> list[dict]:
    """chunks 테이블 insert용 row 리스트. embedding은 embedding/embed.py에서 채움."""
    pieces = chunk_text(text)
    return [
        {
            "document_id": document_id,
            "chunk_index": i,
            "content": piece,
            "token_count": len(piece.split()),
        }
        for i, piece in enumerate(pieces)
    ]
