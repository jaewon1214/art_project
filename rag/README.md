# rag/ — RAG 파이프라인

`collector/`가 모아온 문서(뉴스/정책/공식자료/논문/판례)를 받아서 정제 → 청킹 → 임베딩까지
처리해 DB에 저장하고, 검색 시점엔 이 데이터를 찾아 `search_context()` 하나로 돌려주는 모듈.

## 흐름

```
collector/*.py 문서 1건
  → rag/pipeline/ingest.py (진입점)
      1. normalize + content_hash 완전중복 확인
      2. 근접중복(제목 유사도, pg_trgm) 확인 → 있으면 중단
      3. LLM 관련성 판정 + 카테고리 재분류 + 엔티티/관계 추출 (호출 1번)
         → 주제와 무관하면 여기서 중단, DB에 안 남음
      4. 비한국어 문서(논문 제외)면 한국어로 번역
      5. documents/chunks insert (Postgres)
      6. chunk 임베딩 계산 → chunks.embedding UPDATE
      7. entities/document_entities insert + Neo4j 동기화
```

각 단계는 관련 `.env` 설정(LLM_PROVIDER/EMBEDDING_PROVIDER/NEO4J_URI)이 없으면 조용히
건너뛰고, documents/chunks 저장까지는 항상 진행됨.

## 검색 — search_context()

3번(backend)이 쓰는 팀 공통 인터페이스:

```python
from rag.retrieval.context_builder import search_context

result = search_context(topic="AI 음성복제와 저작권 침해 문제")
# {"contexts": [{"chunk_id", "document_id", "content", "score"}, ...],
#  "sources": [{"document_id", "title", "url", "author", "published_at", "category"}, ...]}
```

내부적으로 벡터 검색(pgvector) + 키워드 검색(Postgres FTS, 한국어 형태소 분석 적용) +
그래프 검색(Neo4j) 세 경로를 돌려서 RRF(Reciprocal Rank Fusion)로 합침. 세 경로 다
"설정 안 돼 있으면 빈 결과만 내고 넘어가는" 방어적 설계라 임베딩/Neo4j 없이도 동작함.

## 폴더 구조

| 폴더 | 역할 |
|---|---|
| `preprocessing/` | HTML 정제, 완전/근접 중복 제거, 한국어 형태소 분석, 번역 |
| `chunking/` | 문서 → 청크 분할 (600단어, 100 overlap) |
| `embedding/` | 청크 → 벡터 (OpenAI text-embedding-3-large, 1536차원 truncate), rate limit 재시도 포함 |
| `entity_extraction/` | LLM 관련성 판정 + 카테고리 분류 + 엔티티/관계 추출 (호출 1번으로 다 처리) |
| `pipeline/` | `ingest_document()` — 위 전체를 문서 1건에 대해 순서대로 실행 |
| `retrieval/` | vector/keyword/graph 검색 + RRF + `search_context()` |
| `scripts/` | 운영/검증용 스크립트 (아래 표) |
| `data/` | 직접 다운받은 논문 PDF 넣는 곳 (`data/<쟁점>/*.pdf`) |

## 운영 스크립트 (`rag/scripts/`)

| 스크립트 | 용도 |
|---|---|
| `db_stats.py` | DB 현황(카테고리/타입별 건수, 과거·최신 분포 등) 확인 |
| `evaluate_search.py` | 검색 정확도(precision@k) 사람 라벨링 테스트 |
| `smoke_test_search.py` | 검색이 0건 없이 그럴듯하게 나오는지 빠른 확인 |
| `ingest_pdfs.py` | `data/<쟁점>/*.pdf` 텍스트 추출 후 적재 |
| `export_papers.py` | 논문만 JSONL로 내보내기 (2번 공유용) |
| `rechunk_documents.py` | 청크 크기 바뀌었을 때 기존 문서 재청킹+재임베딩 |
| `backfill_strip_html.py` | 기존 문서 HTML 잔재 정리 |
| `backfill_news_category.py` | 뉴스 문서 카테고리 재분류 |
| `backfill_retranslate.py` | 번역 불완전한 문서 원본 재수집 후 재번역 |
| `migrate_korean_tokenize.py` | 기존 DB에 한국어 형태소 분석 컬럼 적용 |

전부 저장소 루트에서 `python -m rag.scripts.<이름>`으로 실행.

## 필요한 .env 값

`EMBEDDING_PROVIDER/MODEL/DIM/API_KEY`, `LLM_PROVIDER/MODEL/API_KEY`, `DB_*`, `NEO4J_*` —
루트 `.env.example` 참고. 전부 비워두면 해당 기능만 건너뛰고 수집/저장 자체는 계속 동작함.
