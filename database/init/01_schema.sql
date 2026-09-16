-- =====================================================================
-- "생성형 AI와 음악 창작" — 논문 초안 AI-Agent (RAG + Transformer + LLM)
-- 담당: 1번 (RAG / Data / DB)
-- PostgreSQL + pgvector 스키마  v3 — 팀 리뷰 반영
-- =====================================================================
-- v3에서 반영한 피드백:
--   1. documents: content/url/published_at/document_type 필드 확정 (raw_text → content로 이름 변경)
--   2. chunks: content/chunk_index 필드 확정, section/embedding_model 등 비핵심 필드 제거(MVP 슬림화)
--   3. embedding VECTOR(1536) 확정 — OpenAI text-embedding-3-large(dimensions=1536 truncate), 다국어 검색용 (2026-09)
--   4. paper_citations는 MVP 그대로 유지
--   5. "근거 없는 문장 금지" = DB 제약(NOT NULL) + Backend 검증(파일 하단 예시 쿼리) 이중 구현
--   6. Neo4j는 STRETCH 유지
--   7. Neo4j 구현 시 entities 테이블 필요 (STRETCH 섹션에 포함, Postgres ↔ Neo4j 상호참조 방식 명시)
--   8. Vector + Keyword 결합 스코어링 방식 정의 (파일 하단 "HYBRID SCORE" 예시, RRF 방식 채택)
--
-- MVP(1~5일, 시연 통과에 필수) : sources, documents, chunks, papers, paper_citations
-- STRETCH(시간 남으면)        : entities, document_entities (+ Neo4j graph/schema.cypher)
--
-- 적용: psql -U <user> -d <db> -f schema.sql
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- 제목 유사매칭(선택)

-- =====================================================================
-- ▶ MVP — 이 5개 테이블만으로 "검색 → 초안 → 근거표시" 전체 흐름이 돈다
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. sources : 수집 출처. PPT 기준 뉴스/웹/공개지식(정책·공식자료) 위주
-- ---------------------------------------------------------------------
CREATE TABLE sources (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,                 -- 예: '한국저작권위원회', 'Music Business Worldwide'
    source_type     TEXT NOT NULL,                  -- 'news' | 'webpage' | 'policy' | 'official'
                                                      -- (필요시만) 'paper' | 'case'
    base_url        TEXT,
    trust_level     SMALLINT DEFAULT 3,             -- 1~5, 랭킹 가중치
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 2. documents : 문서 1건 (기사/웹자료/정책 등)
-- ---------------------------------------------------------------------
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,

    title           TEXT NOT NULL,
    content         TEXT NOT NULL,                  -- 정제된 본문 전체 (재청킹 대비 원본 보관; 구 raw_text)
    url             TEXT UNIQUE,
    author          TEXT,

    -- 팀 쟁점 태깅. 최종적으로 쟁점 하나로 좁힌다면 category 값 하나로 수렴해도 되고,
    -- 후보군(저작권/창작자성/음성복제/AI작곡)을 유지한 채 필터링해도 됨.
    category        TEXT NOT NULL,                  -- 예: '저작권' | '창작자성' | '음성복제' | 'AI작곡'

    document_type   TEXT NOT NULL,                  -- 'news' | 'webpage' | 'policy' | 'official' 우선
                                                      -- (필요시) 'paper' | 'case'
    published_at    DATE,
    language        TEXT NOT NULL DEFAULT 'ko',

    content_hash    TEXT UNIQUE,                     -- sha256(normalized content) — 중복수집 방지

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_category      ON documents (category);
CREATE INDEX idx_documents_type          ON documents (document_type);
CREATE INDEX idx_documents_published_at  ON documents (published_at DESC);
CREATE INDEX idx_documents_source        ON documents (source_id);
CREATE INDEX idx_documents_title_trgm    ON documents USING GIN (title gin_trgm_ops);

-- ---------------------------------------------------------------------
-- 3. chunks : RAG 검색 최소 단위 (Vector + Keyword 동시 지원)
-- ---------------------------------------------------------------------
-- embedding dimension 확정: 1536 (OpenAI text-embedding-3-large, dimensions 파라미터로 truncate해서 씀
--   — 원래 차원은 3072지만 1536으로 잘라서 받음, rag/embedding/embed.py 참고).
--   다국어(한국어+영어) 검색 성능 때문에 -3-small 대신 -3-large로 확정함(2026-09).
CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,

    chunk_index     INTEGER NOT NULL,                -- 문서 내 순서
    content         TEXT NOT NULL,
    -- 한국어 형태소 분석(조사/어미 제거) 결과 — 검색 인덱싱 전용, 화면 표시는 content 그대로 사용.
    -- rag/preprocessing/korean_tokenize.py(kiwipiepy)가 채움. 2026-09-16 추가:
    -- to_tsvector('simple', content)만 쓰면 "저작권"으로 검색해도 본문의 "저작권을"과 매칭이
    -- 안 되는 문제가 있어서(simple은 조사를 안 떼어냄), content_tokenized를 따로 두고
    -- content_tsv가 이 컬럼 기준으로 생성되게 함 — 쿼리 쪽(keyword_search.py)도 동일하게 토큰화.
    content_tokenized TEXT,
    token_count     INTEGER,

    content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content_tokenized, content))) STORED,
    embedding       VECTOR(1536),                     -- text-embedding-3-large, dimensions=1536 truncate (위 78번째 줄 주석 참고)

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (document_id, chunk_index)
);

CREATE INDEX idx_chunks_document    ON chunks (document_id);
CREATE INDEX idx_chunks_content_tsv ON chunks USING GIN (content_tsv);
CREATE INDEX idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ---------------------------------------------------------------------
-- 4. papers : LLM이 최종 정제한 논문 초안 (3번 backend가 기록)
-- ---------------------------------------------------------------------
CREATE TABLE papers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    topic           TEXT NOT NULL,                    -- 사용자(강사)가 입력한 연구 주제/제목
    title           TEXT,

    abstract        TEXT,
    introduction    TEXT,
    body            TEXT,
    conclusion      TEXT,

    status          TEXT NOT NULL DEFAULT 'draft',     -- 'draft' | 'final'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_papers_created_at ON papers (created_at DESC);

-- ---------------------------------------------------------------------
-- 5. paper_citations : "근거가 보이게" + "없는 사실 금지"를 DB로 강제하는 테이블
-- ---------------------------------------------------------------------
-- 최종 초안의 각 섹션이 어떤 chunk(=어떤 문서)를 근거로 썼는지 기록.
CREATE TABLE paper_citations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id        UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    section         TEXT NOT NULL,                     -- 'introduction' | 'body' | 'conclusion'

    chunk_id        UUID NOT NULL REFERENCES chunks(id) ON DELETE RESTRICT,
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,  -- 조회 편의용 비정규화

    claim_text      TEXT NOT NULL,                     -- 이 근거가 뒷받침하는 초안 내 문장/주장 (검증 대상이라 NOT NULL)
    relevance_score REAL,                                -- 검색 시 유사도/결합 점수 (근거 채택 기준 추적)

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_paper_citations_paper ON paper_citations (paper_id);
CREATE INDEX idx_paper_citations_chunk ON paper_citations (chunk_id);

-- ---------------------------------------------------------------------
-- "근거 없는 문장 금지" 검증 (항목 5) — DB + Backend 이중 구현
-- ---------------------------------------------------------------------
-- DB 쪽 강제: paper_citations.claim_text/chunk_id/document_id를 NOT NULL로 걸어
--   "근거 없는 citation row" 자체가 존재할 수 없게 함.
-- Backend 쪽 강제: papers.status를 'draft' → 'final'로 바꾸기 전에, 아래 쿼리로
--   "citation이 하나도 없는 섹션"이 있는지 확인하고 있으면 커밋(=final 전환)을 막는다.
--   3번 담당 LLM 파이프라인이 이 쿼리(또는 동일 로직)를 최종화 직전에 호출.
--
-- 예시: paper_id 하나에 대해 섹션별 citation 개수 확인
-- SELECT s.section,
--        COUNT(pc.id) AS citation_count
-- FROM unnest(ARRAY['introduction','body','conclusion']) AS s(section)
-- LEFT JOIN paper_citations pc
--        ON pc.paper_id = $1 AND pc.section = s.section
-- GROUP BY s.section;
-- → citation_count = 0 인 섹션이 있으면 해당 섹션은 최종본에서 제외하거나 재생성 요청.

-- =====================================================================
-- ▶ HYBRID SCORE — Vector + Keyword 결합 스코어링 (항목 8)
-- =====================================================================
-- 벡터 점수(코사인 유사도)와 키워드 점수(ts_rank)는 스케일이 달라서 단순 가중합은
-- 정규화가 필요함. MVP에서는 정규화가 필요 없는 RRF(Reciprocal Rank Fusion)를 권장:
--   각 방식으로 따로 Top-N을 뽑아 "순위"만 이용해 점수를 합침 → score = Σ 1/(k + rank)
--   (k=60이 일반적 기본값)
--
-- 예시 쿼리 (category 필터 포함, RRF로 벡터+키워드 결합):
--
-- WITH vector_rank AS (
--     SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rnk
--     FROM chunks c JOIN documents d ON d.id = c.document_id
--     WHERE d.category = $2
--     ORDER BY embedding <=> $1 LIMIT 50
-- ),
-- keyword_rank AS (
--     SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(content_tsv, plainto_tsquery('simple', $3)) DESC) AS rnk
--     FROM chunks c JOIN documents d ON d.id = c.document_id
--     WHERE d.category = $2 AND content_tsv @@ plainto_tsquery('simple', $3)
--     ORDER BY rnk LIMIT 50
-- )
-- SELECT COALESCE(v.id, k.id) AS chunk_id,
--        COALESCE(1.0 / (60 + v.rnk), 0) + COALESCE(1.0 / (60 + k.rnk), 0) AS score
-- FROM vector_rank v
-- FULL OUTER JOIN keyword_rank k ON v.id = k.id
-- ORDER BY score DESC
-- LIMIT 10;
--
-- (대안) 가중합 방식이 필요하면: score = alpha * norm(vector_score) + (1-alpha) * norm(ts_rank)
--   — 이 경우 min-max 정규화를 먼저 해야 해서 구현이 더 복잡함. MVP는 RRF로 시작 권장.


-- =====================================================================
-- ▶ STRETCH — 시간이 남으면 추가 (Neo4j 그래프 하이브리드 검색용)
--   MVP 없이도 시연(초안 3편 생성)은 통과 가능. 우선순위 최하위.
--   ※ 항목 7: Neo4j를 실제로 구현하기로 하면 아래 entities 테이블이 반드시 필요함
--     (Neo4j 노드와 1:1로 대응하는 관계형 사본이 있어야 Postgres 쪽 검색 결과와 연결 가능).
-- =====================================================================

-- 6. entities : Neo4j 노드의 관계형 사본
CREATE TABLE entities (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              TEXT NOT NULL,
    normalized_name   TEXT NOT NULL,
    entity_type       TEXT NOT NULL,                    -- 'Artist' | 'Company' | 'AIModel' | 'Topic'
                                                          -- | 'Case' | 'Law'
    description       TEXT,
    neo4j_node_key    TEXT,                              -- Neo4j 쪽 MERGE key (보통 normalized_name)
                                                           -- ↕ Neo4j 노드의 pg_entity_id 프로퍼티가 이 row의 id를 가리킴
                                                           --   (Postgres ↔ Neo4j 상호참조, graph/schema.cypher 참고)

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (normalized_name, entity_type)
);

CREATE INDEX idx_entities_type ON entities (entity_type);

-- 7. document_entities : 문서/청크 ↔ 개체 연결
CREATE TABLE document_entities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id        UUID REFERENCES chunks(id) ON DELETE CASCADE,
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

    relation_type   TEXT,                                -- 'DISCUSSES' | 'MENTIONS' | 'DEVELOPS'
                                                           -- | 'RELATED_TO' | 'CITES'
    confidence      REAL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_doc_entities_document ON document_entities (document_id);
CREATE INDEX idx_doc_entities_entity   ON document_entities (entity_id);
CREATE INDEX idx_doc_entities_chunk    ON document_entities (chunk_id);
