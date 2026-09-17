"""
Postgres의 entities / document_entities → Neo4j 노드/관계로 적재.

entity_extraction/sync.py의 extract_and_store()가 만들어주는 두 리스트를 그대로 받는다:
    load_entities(entities_for_graph)
    load_relations(relations_for_graph)

Postgres <-> Neo4j 상호 참조 규칙:
  - entities.neo4j_node_key  → Neo4j 쪽 MERGE key로 사용
  - Neo4j 노드의 pg_entity_id 프로퍼티 → entities.id를 가리킴 (역방향 참조)

Cypher에서 라벨/관계타입은 파라미터 바인딩이 안 되기 때문에(문자열로 직접 넣어야 함),
known_types.ENTITY_TYPES / RELATION_TYPES 화이트리스트에 있는 값만 f-string으로 넣는다 —
그 밖의 값이 섞여 들어오면 여기서 즉시 ValueError로 막는다(Cypher 인젝션 방지).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from database.config import get_neo4j_driver
from database.neo4j.known_types import ENTITY_TYPES, RELATION_TYPES


def load_entities(entities: Iterable[dict]) -> None:
    """
    entities 각 row를 Neo4j 노드로 MERGE.
    entity dict 예: {"neo4j_node_key": "suno", "entity_type": "AIModel", "name": "Suno", "id": "<uuid>"}
    """
    rows = list(entities)
    if not rows:
        return

    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        entity_type = row["entity_type"]
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"알 수 없는 entity_type: {entity_type!r} (허용값: {ENTITY_TYPES})")
        by_type[entity_type].append(
            {"key": row["neo4j_node_key"], "name": row["name"], "pg_entity_id": str(row["id"])}
        )

    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            for entity_type, type_rows in by_type.items():
                session.run(
                    f"""
                    UNWIND $rows AS row
                    MERGE (n:{entity_type} {{key: row.key}})
                    SET n.name = row.name, n.pg_entity_id = row.pg_entity_id
                    """,
                    rows=type_rows,
                )
    finally:
        driver.close()


def load_relations(document_entities: Iterable[dict]) -> None:
    """
    document_entities 각 row를 (:Paper)-[관계]->(:엔티티)로 MERGE.
    row 예: entity_extraction/sync.py의 extract_and_store()가 반환하는 relations_for_graph 형식
    ({"document_id", "document_key", "document_title", "category", "published_at",
      "entity_neo4j_key", "entity_type", "relation_type", "confidence"})

    Paper 노드는 "생성된 논문"이 아니라 "수집된 원본 문서" 1건을 가리킴 (graph/schema.cypher 주석 참고,
    key=documents.id, pg_document_id=documents.id).
    """
    rows = list(document_entities)
    if not rows:
        return

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        entity_type = row["entity_type"]
        relation_type = row["relation_type"]
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"알 수 없는 entity_type: {entity_type!r} (허용값: {ENTITY_TYPES})")
        if relation_type not in RELATION_TYPES:
            raise ValueError(f"알 수 없는 relation_type: {relation_type!r} (허용값: {RELATION_TYPES})")
        grouped[(entity_type, relation_type)].append(
            {
                "document_key": row["document_key"],
                "pg_document_id": str(row["document_id"]),
                "document_title": row["document_title"],
                "category": row["category"],
                "published_at": row["published_at"],
                "entity_key": row["entity_neo4j_key"],
                "confidence": row["confidence"],
            }
        )

    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            for (entity_type, relation_type), group_rows in grouped.items():
                session.run(
                    f"""
                    UNWIND $rows AS row
                    MERGE (p:Paper {{key: row.document_key}})
                    SET p.pg_document_id = row.pg_document_id,
                        p.title = row.document_title,
                        p.category = row.category,
                        p.published_at = row.published_at
                    MERGE (e:{entity_type} {{key: row.entity_key}})
                    MERGE (p)-[r:{relation_type}]->(e)
                    SET r.confidence = row.confidence
                    """,
                    rows=group_rows,
                )
    finally:
        driver.close()


if __name__ == "__main__":
    print("사용 예: entity_extraction.sync.extract_and_store()가 반환한 두 리스트를 각각")
    print("load_entities(entities_for_graph) / load_relations(relations_for_graph)에 넘기면 됨.")
    print("직접 테스트하려면 pipeline/ingest.py를 문서 1건으로 돌려보는 걸 추천.")
