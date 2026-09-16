"""
chunks.content -> chunks.embedding을 채우는 모듈.

EMBEDDING_PROVIDER=openai (.env 기본값) — text-embedding-3-large.
한국어(뉴스/법령)+영어(논문/해외정책) 섞인 데이터라 다국어(cross-lingual) 검색 성능이 더 좋은
large 모델로 씀. 단, OpenAI embeddings API의 dimensions 파라미터로 출력을 EMBEDDING_DIM(1536)
으로 잘라서 받기 때문에 database/init/01_schema.sql의 VECTOR(1536)은 그대로 유지됨(스키마
변경/재생성 불필요) — text-embedding-3-large의 원래 차원은 3072지만 여기선 안 씀.

⚠️ 이미 text-embedding-3-small로 임베딩해서 저장한 chunks가 있다면, 모델이 다르면 벡터 공간이
달라서 같이 검색하면 정확도가 떨어짐 — 기존 chunks.embedding은 재임베딩(재계산) 필요.

2026-09-16: rate limit(429) 재시도 로직 추가 — 예전엔 재시도가 없어서, news 볼륨을 키운
뒤 한 번에 수백 건씩 수집할 때 rate limit에 걸리면 그 문서는 chunks는 저장되고 embedding만
NULL로 남는 문제가 있었음(벡터검색에서 누락, run_collectors.py의 실패 카운트로도 안 잡힘 —
ingest_document()는 documents/chunks insert 후 commit부터 하고 그 다음에 임베딩을 시도하기
때문). collector/paper_collector.py의 Semantic Scholar 429 재시도와 같은 패턴(지수 백오프 +
Retry-After 헤더 우선 사용)으로 맞춤.
"""
from __future__ import annotations

import time

from rag.config import EMBEDDING_API_KEY, EMBEDDING_DIM, EMBEDDING_MODEL, EMBEDDING_PROVIDER

# OpenAI embeddings API는 한 번에 훨씬 많이 받아주지만, 안전하게 배치 단위로 나눠서 호출.
_BATCH_SIZE = 100

_MAX_RETRIES = 3
_RETRY_BACKOFF_SEC = 5  # 재시도할 때마다 5, 10, 15초... 늘려가며 대기(Retry-After 헤더 있으면 그걸 우선 사용)


def _embed_openai(texts: list[str]) -> list[list[float]]:
    from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

    client = OpenAI(api_key=EMBEDDING_API_KEY)
    vectors: list[list[float]] = []

    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                # dimensions=EMBEDDING_DIM: large 모델의 원래 3072차원을 1536으로 잘라서 받음
                # (OpenAI의 matryoshka 방식 truncation — 스키마 VECTOR(1536)과 맞추기 위함).
                resp = client.embeddings.create(
                    model=EMBEDDING_MODEL or "text-embedding-3-large",
                    input=batch,
                    dimensions=EMBEDDING_DIM,
                )
                vectors.extend(d.embedding for d in resp.data)
                last_error = None
                break
            except RateLimitError as e:
                wait = _RETRY_BACKOFF_SEC * (attempt + 1)
                retry_after = getattr(getattr(e, "response", None), "headers", {}).get("retry-after")
                if retry_after:
                    try:
                        wait = int(float(retry_after))
                    except (TypeError, ValueError):
                        pass
                print(
                    f"[embed] 배치 {i}~{i + len(batch)} rate limit — {wait}초 대기 후 재시도 "
                    f"({attempt + 1}/{_MAX_RETRIES})"
                )
                last_error = e
                time.sleep(wait)
            except (APIConnectionError, APIStatusError) as e:
                print(
                    f"[embed] 배치 {i}~{i + len(batch)} 요청 실패({e}) — {_RETRY_BACKOFF_SEC}초 후 재시도 "
                    f"({attempt + 1}/{_MAX_RETRIES})"
                )
                last_error = e
                time.sleep(_RETRY_BACKOFF_SEC)

        if last_error is not None:
            raise last_error

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
