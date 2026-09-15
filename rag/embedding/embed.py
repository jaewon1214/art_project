"""
chunks.content -> chunks.embedding을 채우는 모듈.

EMBEDDING_PROVIDER=openai (.env 기본값) — text-embedding-3-small, 1536차원.
database/schema.sql의 VECTOR(1536)이 이미 이 값 기준이라 차원 변경/재생성 필요 없음.
"""
from __future__ import annotations

from rag.config import EMBEDDING_API_KEY, EMBEDDING_DIM, EMBEDDING_MODEL, EMBEDDING_PROVIDER

# OpenAI embeddings API는 한 번에 훨씬 많이 받아주지만, 안전하게 배치 단위로 나눠서 호출.
_BATCH_SIZE = 100


def _embed_openai(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=EMBEDDING_API_KEY)
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        resp = client.embeddings.create(model=EMBEDDING_MODEL or "text-embedding-3-small", input=batch)
        vectors.extend(d.embedding for d in resp.data)
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    texts와 같은 길이의 임베딩 벡터 리스트 반환. 각 벡터 길이는 EMBEDDING_DIM과 같아야 함.
    texts가 비어있으면 빈 리스트 반환(호출부에서 매번 길이 체크 안 해도 되게).
    """
    if not texts:
        return []

    if not EMBEDDING_PROVIDER:
        raise NotImplementedError(
            "EMBEDDING_PROVIDER가 .env에 설정되지 않았습니다. "
            ".env(EMBEDDING_PROVIDER/EMBEDDING_MODEL/EMBEDDING_DIM/EMBEDDING_API_KEY)를 채우세요."
        )

    if EMBEDDING_PROVIDER == "openai":
        vectors = _embed_openai(texts)
    else:
        raise NotImplementedError(f"'{EMBEDDING_PROVIDER}' provider 구현 필요 (embedding/embed.py)")

    for v in vectors:
        if len(v) != EMBEDDING_DIM:
            raise ValueError(
                f"'{EMBEDDING_MODEL}' 모델이 반환한 벡터 길이({len(v)})가 "
                f"EMBEDDING_DIM({EMBEDDING_DIM})과 다릅니다 — .env의 EMBEDDING_DIM을 맞추세요."
            )
    return vectors


def embedding_to_pgvector_literal(vec: list[float]) -> str:
    """psycopg2로 vector 컬럼에 넣을 때 쓰는 pgvector 리터럴 문자열 변환. 예: '[0.1,0.2,...]'"""
    if len(vec) != EMBEDDING_DIM:
        raise ValueError(f"벡터 길이({len(vec)})가 EMBEDDING_DIM({EMBEDDING_DIM})과 다릅니다.")
    return "[" + ",".join(str(x) for x in vec) + "]"


if __name__ == "__main__":
    sample = ["Suno가 새 버전을 출시하며 저작권 침해 논란이 다시 불거졌다."]
    vecs = embed_texts(sample)
    print(f"{len(vecs)}개 벡터, 차원={len(vecs[0])}")
