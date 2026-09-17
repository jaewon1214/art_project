"""
"데이터가 들어올 때마다 자동으로 연결"의 실제 진입점.

collectors/*.collect()가 만든 raw dict 1건을 ingest_document()에 넣으면:
    normalize -> 중복(content_hash 완전일치 + title 근접중복) 확인
    -> (LLM_PROVIDER 설정돼 있으면) 관련성 판정 — 주제와 무관하면 여기서 저장하지 않고 중단
       (관련성 있으면 같이 나온 category로 collector가 넘긴 category를 덮어씀 — 실제 내용 기준)
    -> (관련성 있고, document_type != "paper" 이고, language != "ko" 인 문서만) 한국어로 번역
       — 영어 논문(arXiv/Semantic Scholar)은 원문 학술 용어 보존을 위해 번역하지 않음
    -> documents/chunks insert(번역됐으면 번역문 기준) -> (EMBEDDING_PROVIDER 설정돼 있으면) chunk 임베딩 계산 후 저장
    -> (관련성 판정 때 계산해둔 엔티티/관계를 그대로) entities/document_entities 저장
    -> (NEO4J_URI 설정돼 있으면) Neo4j 노드/관계 동기화
까지 한 번에 처리됨. 관련성 판정과 엔티티 추출은 LLM 호출 1번으로 같이 끝내고 그 결과를 재사용 —
문서 1건당 관련성판정 LLM 호출은 정확히 1번(구성 안 돼 있으면 0번), 번역 대상이면 추가로 LLM
호출이 붙는다(문서 길이에 따라 여러 번 — preprocessing/translate.py의 CHUNK_SIZE_CHARS 단위 분할).
content_hash는 번역 전 원문 기준으로 계산해서 저장하므로, 같은 원문 기사를 다시 수집해도
번역 결과와 무관하게 정상적으로 중복 처리된다.

LLM_PROVIDER/EMBEDDING_PROVIDER/NEO4J_URI가 .env에 없으면 그 단계만 조용히 건너뛰고
documents/chunks 저장까지는 항상 정상 진행(어느 한 단계 실패/미구성이 수집 자체를 막지 않게).
"""
from __future__ import annotations

from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal
from rag.entity_extraction import extractor
from rag.entity_extraction.sync import store_extraction
from database.neo4j.loader import load_entities, load_relations
from rag.preprocessing.dedupe import content_hash, find_near_duplicate, is_duplicate
from rag.preprocessing.normalize_metadata import normalize
from rag.preprocessing.translate import translate_to_korean


def get_or_create_source(conn, name: str, source_type: str) -> int:
    """sources.name 기준으로 찾고, 없으면 새로 만들어 id 반환."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM sources WHERE name = %s;", (name,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "INSERT INTO sources (name, source_type) VALUES (%s, %s) RETURNING id;",
            (name, source_type),
        )
        return cur.fetchone()[0]


def ingest_document(raw_doc: dict, sync_graph: bool = True) -> dict:
    """
    raw_doc: collectors 규약대로 title/content/url/author/category/document_type/
             published_at/language/source_name 키를 가진 dict.

    반환:
      {"status": "inserted", "document_id": <uuid>}          — 정상 저장됨
      {"status": "duplicate"}                                 — 이미 수집된 문서(content_hash 완전 일치)
      {"status": "near_duplicate", "similar_to": <title>}      — 같은 document_type 안에서 제목이
                                                                  기존 문서와 매우 유사(pg_trgm) — 저장 안 함
      {"status": "irrelevant", "reason": <str>}                — LLM이 주제와 무관하다고 판정, 저장 안 함
    """
    doc = normalize(raw_doc)
    h = content_hash(doc["content"])

    with config.get_connection() as conn:
        if is_duplicate(conn, h):
            return {"status": "duplicate"}

        # 근접 중복(제목 유사도) — 완전 일치는 아니지만 같은 사건을 다른 매체가 비슷하게 보도한
        # 경우 등을 잡음. LLM 호출(비용 발생) 전에 걸러서 불필요한 관련성판정 비용도 같이 아낌.
        near_dup_title = find_near_duplicate(conn, doc["title"], doc["document_type"])
        if near_dup_title:
            return {"status": "near_duplicate", "similar_to": near_dup_title}

        # 관련성 판정 + 엔티티/관계 추출 — documents insert 전에 LLM 호출 1번.
        # "꼭 관련된 내용으로만 수집" 요건: is_relevant=False면 여기서 그냥 끝, DB에 아무것도 안 남음.
        extraction: dict | None = None
        if config.LLM_PROVIDER:
            extraction = extractor.analyze_document(doc["content"], document_type=doc["document_type"])
            if not extraction["is_relevant"]:
                return {"status": "irrelevant", "reason": extraction.get("relevance_reason", "")}
            # collector가 넘긴 category(검색쿼리/사람이 미리 정한 값)는 1차 힌트일 뿐이고,
            # 문서 실제 내용을 본 LLM 분류 결과가 있으면 그걸로 덮어씀 — news_collector.py가
            # 모든 기사에 category="음성복제"를 하드코딩하던 버그를 여기서 근본적으로 해결.
            if extraction.get("category"):
                doc["category"] = extraction["category"]

        # 번역 — "영어논문은 번역 필요없음, 나머지 데이터만 번역" 요구사항:
        # document_type == "paper"면 원문(영어) 그대로 두고, 그 외에 language != "ko"인 문서만 번역.
        # 관련성 판정을 이미 통과한 문서에 대해서만 호출하므로 버려질 문서에 번역 비용을 쓰지 않는다.
        if config.LLM_PROVIDER and doc["document_type"] != "paper" and doc["language"] != "ko":
            doc["title"] = translate_to_korean(doc["title"]) or doc["title"]
            doc["content"] = translate_to_korean(doc["content"])
            doc["language"] = "ko"

        source_id = get_or_create_source(conn, raw_doc["source_name"], doc["document_type"])

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (source_id, title, content, url, author, category,
                                        document_type, published_at, language, content_hash)
                VALUES (%(source_id)s, %(title)s, %(content)s, %(url)s, %(author)s, %(category)s,
                        %(document_type)s, %(published_at)s, %(language)s, %(content_hash)s)
                RETURNING id;
                """,
                {**doc, "source_id": source_id, "content_hash": h},
            )
            document_id = cur.fetchone()[0]

            chunk_rows = build_chunk_rows(document_id, doc["content"])
            chunk_id_by_index: dict[int, str] = {}
            for row in chunk_rows:
                cur.execute(
                    """
                    INSERT INTO chunks (document_id, chunk_index, content, content_tokenized, token_count)
                    VALUES (%(document_id)s, %(chunk_index)s, %(content)s, %(content_tokenized)s, %(token_count)s)
                    RETURNING id;
                    """,
                    row,
                )
                chunk_id_by_index[row["chunk_index"]] = cur.fetchone()[0]
        conn.commit()

        # 임베딩 — chunk 저장 직후, 같은 트랜잭션 밖에서 계산해서 UPDATE (API 호출은 커밋 밖에서).
        #
        # 2026-09-16: 여기서 실패(재시도 소진 등)해도 예외를 밖으로 던지지 않도록 감쌈 — 예전엔
        # 이 블록에서 터진 예외가 ingest_document() 밖으로 그대로 나가서: (1) 바로 위에서 이미
        # commit된 documents/chunks는 그대로 DB에 남고, (2) content_hash가 이미 DB에 있으니 다음
        # 수집 때 "완전중복"으로 처리돼 다시는 재시도되지 않고, (3) 아래 엔티티/관계 저장 블록까지
        # 통째로 스킵되는 "반쪽 상태" 문서가 영구적으로 생겼음(embedding NULL -> 벡터검색 누락,
        # entities도 없음). run_collectors.py는 이걸 "failed"로만 카운트해서 실제로 저장은 됐다는
        # 사실도 로그에서 드러나지 않았음. 이제는 실패해도 계속 진행해서 엔티티 저장/Neo4j 동기화는
        # 정상적으로 이어지고, 반환값의 embedding_failed로 이 사실을 호출부에 알림 — 재임베딩은
        # rag/scripts/backfill_missing_embeddings.py(embedding IS NULL인 chunk를 찾아 재계산)로 처리.
        embedding_failed = False
        if config.EMBEDDING_PROVIDER and chunk_rows:
            try:
                vectors = embed_texts([row["content"] for row in chunk_rows])
                with conn.cursor() as cur:
                    for row, vec in zip(chunk_rows, vectors):
                        cur.execute(
                            "UPDATE chunks SET embedding = %s::vector WHERE id = %s;",
                            (embedding_to_pgvector_literal(vec), chunk_id_by_index[row["chunk_index"]]),
                        )
                conn.commit()
            except Exception as e:  # noqa: BLE001 — 아래 엔티티 저장까지 막으면 안 됨(위 주석 참고)
                conn.rollback()
                embedding_failed = True
                print(
                    f"[ingest] document_id={document_id} 임베딩 실패({e}) — chunks는 저장됐지만 "
                    "embedding은 NULL로 남음. backfill_missing_embeddings.py로 나중에 재계산할 것."
                )

        # 엔티티/관계 저장 — 위에서 이미 계산해둔 extraction 재사용 (LLM 재호출 없음).
        # 임베딩 성공 여부와 무관하게 항상 시도 — 둘은 독립적인 단계라 하나가 실패해도 다른 하나는
        # 정상 진행돼야 함.
        entities_for_graph: list[dict] = []
        relations_for_graph: list[dict] = []
        if extraction is not None:
            doc_meta = {"title": doc["title"], "category": doc["category"], "published_at": doc["published_at"]}
            entities_for_graph, relations_for_graph = store_extraction(conn, document_id, doc_meta, extraction)
            conn.commit()

    if sync_graph and config.NEO4J_URI and entities_for_graph:
        load_entities(entities_for_graph)
        load_relations(relations_for_graph)

    result = {"status": "inserted", "document_id": document_id}
    if embedding_failed:
        result["embedding_failed"] = True
    return result


if __name__ == "__main__":
    # 동작 확인용 샘플 1건 (실제 수집은 scripts/run_collectors.py, PDF는 scripts/ingest_pdfs.py로)
    sample = {
        "title": "테스트 기사 — Suno 저작권 논란",
        "content": (
            "Suno가 새 버전을 출시하며 저작권 침해 논란이 다시 불거졌다. "
            "하이브는 이에 대응해 자체 AI 정책을 발표했다."
        ),
        "url": "https://example.com/test-article-1",
        "author": None,
        "category": "저작권",
        "document_type": "news",
        "published_at": None,
        "language": "ko",
        "source_name": "테스트 소스",
    }
    print(ingest_document(sample))
