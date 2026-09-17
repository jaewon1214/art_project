"""
extractor.analyze_document()의 결과를 Postgres(entities/document_entities)에 저장하고,
graph/loader.py에 바로 넘길 수 있는 형태(entities_for_graph, relations_for_graph)로 돌려줌.

store_extraction()은 LLM을 호출하지 않는다(이미 계산된 extraction 결과를 받기만 함) — 그래야
pipeline/ingest.py가 "documents insert 전에" 관련성만 먼저 확인하고, "documents insert 후에"
같은 LLM 호출 결과를 재사용해서 저장까지 끝낼 수 있다(LLM 호출은 문서당 딱 1번).
"""
from __future__ import annotations

import re

from rag.entity_extraction import extractor
from database.neo4j.known_types import ENTITY_TYPES, RELATION_TYPES


def normalize_name(name: str) -> str:
    """entities.normalized_name / Neo4j MERGE key로 쓰는 정규화 문자열."""
    n = name.strip().lower()
    n = re.sub(r"\s+", "_", n)
    n = re.sub(r"[^\w가-힣]", "", n)  # 영문/숫자/밑줄/한글만 남김
    return n


def get_or_create_entity(conn, entity_type: str, name: str) -> dict:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"알 수 없는 entity_type: {entity_type!r} (허용값: {ENTITY_TYPES})")

    norm = normalize_name(name)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, neo4j_node_key, name FROM entities WHERE normalized_name = %s AND entity_type = %s;",
            (norm, entity_type),
        )
        row = cur.fetchone()
        if row:
            return {"id": row[0], "neo4j_node_key": row[1], "name": row[2], "entity_type": entity_type}

        cur.execute(
            """
            INSERT INTO entities (name, normalized_name, entity_type, neo4j_node_key)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (normalized_name, entity_type) DO UPDATE SET name = entities.name
            RETURNING id, neo4j_node_key, name;
            """,
            (name, norm, entity_type, norm),
        )
        row = cur.fetchone()
        return {"id": row[0], "neo4j_node_key": row[1], "name": row[2], "entity_type": entity_type}


def link_document_entity(
    conn, document_id, entity_id, relation_type: str, confidence: float | None = None, chunk_id=None
) -> None:
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"알 수 없는 relation_type: {relation_type!r} (허용값: {RELATION_TYPES})")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM document_entities
            WHERE document_id = %s AND entity_id = %s AND relation_type = %s
            LIMIT 1;
            """,
            (document_id, entity_id, relation_type),
        )
        if cur.fetchone():
            return  # 이미 연결돼 있음 (재실행 대비 — idempotent)

        cur.execute(
            """
            INSERT INTO document_entities (document_id, chunk_id, entity_id, relation_type, confidence)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (document_id, chunk_id, entity_id, relation_type, confidence),
        )


def store_extraction(conn, document_id, doc_meta: dict, extraction: dict) -> tuple[list[dict], list[dict]]:
    """
    extraction: extractor.analyze_document()가 반환한 dict (이미 계산됨 — 여기서 LLM 호출 안 함).
    doc_meta: {"title": str, "category": str, "published_at": date | None} — Neo4j Paper 노드 프로퍼티용.

    반환: (entities_for_graph, relations_for_graph) — graph.loader.load_entities/load_relations에 바로 전달.
    """
    entity_lookup: dict[tuple[str, str], dict] = {}
    entities_for_graph: list[dict] = []

    def _register(entity_type: str, name: str) -> dict:
        stored = get_or_create_entity(conn, entity_type, name)
        key = (normalize_name(name), entity_type)
        if key not in entity_lookup:
            entity_lookup[key] = stored
            entities_for_graph.append(
                {
                    "id": stored["id"],
                    "neo4j_node_key": stored["neo4j_node_key"],
                    "entity_type": stored["entity_type"],
                    "name": stored["name"],
                }
            )
        return stored

    for e in extraction.get("entities", []):
        _register(e["entity_type"], e["name"])

    relations_for_graph: list[dict] = []
    document_key = str(document_id)
    published_at = doc_meta.get("published_at")
    for r in extraction.get("relations", []):
        key = (normalize_name(r["entity_name"]), r["entity_type"])
        stored = entity_lookup.get(key) or _register(r["entity_type"], r["entity_name"])

        link_document_entity(conn, document_id, stored["id"], r["relation_type"], r["confidence"])

        relations_for_graph.append(
            {
                "document_id": document_id,
                "document_key": document_key,
                "document_title": doc_meta.get("title"),
                "category": doc_meta.get("category"),
                "published_at": published_at.isoformat() if published_at else None,
                "entity_neo4j_key": stored["neo4j_node_key"],
                "entity_type": stored["entity_type"],
                "relation_type": r["relation_type"],
                "confidence": r["confidence"],
            }
        )

    return entities_for_graph, relations_for_graph


def extract_and_store(
    conn, document_id, doc_meta: dict, text: str, document_type: str | None = None
) -> tuple[list[dict], list[dict]]:
    """편의 함수: LLM 호출(analyze_document) + 저장(store_extraction)을 한 번에.
    단독 테스트/스크립트용 — pipeline/ingest.py는 관련성 게이팅 때문에 두 단계를 직접 나눠서 씀.
    document_type: case/policy면 analyze_document()가 더 긴 스니펫을 씀(extractor.py 참고) —
    모르면 생략해도 됨(기존 동작과 동일)."""
    extraction = extractor.analyze_document(text, document_type=document_type)
    return store_extraction(conn, document_id, doc_meta, extraction)
