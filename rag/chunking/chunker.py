"""
문서를 chunks 테이블에 넣을 단위로 분할.

지금은 단어(공백) 기준 슬라이딩 윈도우로 구현 — 토큰 기준으로 더 정확하게 하고 싶으면
tiktoken 등으로 교체 (embedding 모델이 정해지면 그 모델의 tokenizer에 맞추는 게 정확함).

2026-09-16: build_chunk_rows()가 chunk마다 content_tokenized(한국어 형태소 분석 결과)도 같이
계산해서 넣도록 확장 — chunks.content_tsv가 content_tokenized를 기준으로 생성되게 스키마를
바꿨음(rag/preprocessing/korean_tokenize.py, database/init/01_schema.sql 참고). 화면에 보여줄
원문(content)과 검색 인덱싱용 텍스트(content_tokenized)를 분리한 것.
"""
from __future__ import annotations

from rag.preprocessing.korean_tokenize import tokenize_for_search

DEFAULT_CHUNK_SIZE = 600   # 단어 수 기준 (2026-09-16: 300 -> 600, 검색 맥락 풍부화 목적)
DEFAULT_OVERLAP = 100      # 2026-09-16: 50 -> 100 (청크 커진 비율에 맞춰 겹침도 같이 늘림)


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
    """chunks 테이블 insert용 row 리스트. embedding은 embedding/embed.py에서 채움.

    content_tokenized가 비어있게(형태소 분석 결과 없음) 나오는 극단적인 경우(숫자/기호뿐인
    chunk 등)를 대비해 원문(content)으로 폴백 — content_tsv 생성식에도 동일하게
    coalesce(content_tokenized, content) 처리가 이중으로 돼있음(schema.sql 참고)."""
    pieces = chunk_text(text)
    return [
        {
            "document_id": document_id,
            "chunk_index": i,
            "content": piece,
            "content_tokenized": tokenize_for_search(piece) or piece,
            "token_count": len(piece.split()),
        }
        for i, piece in enumerate(pieces)
    ]
