"""
Neo4j 기반 그래프 검색 — Vector/Keyword Search랑 짝을 이루는 세 번째 검색 경로.

loader.py는 Postgres -> Neo4j로 "쓰는" 쪽이고, 이 모듈은 반대로 Neo4j에서 "찾아 읽는" 쪽.

방식: query_text에서 뽑은 단어들과 이름이 겹치는 엔티티(Artist/Company/AIModel/Topic/Case/Law)를
Neo4j에서 찾고, 그 엔티티랑 연결된 Paper 노드(-> documents)를 "매칭된 엔티티 개수"로 랭킹한 뒤,
Postgres에서 그 문서들의 chunk를 전부 끌어와 후보로 반환한다.

반환 형식은 vector_search/keyword_search랑 동일 — [{"chunk_id","document_id","content","rank"}] —
그래서 hybrid_rrf.reciprocal_rank_fusion()에 그대로 같이 넣을 수 있다.

Neo4j가 아직 설정 안 됐거나(연결 실패) 매칭되는 엔티티가 없으면 빈 리스트를 반환 — 그래프 신호
없이도 vector+keyword만으로 검색이 계속 동작해야 하므로(다른 검색 함수들과 동일한 방어적 설계).
"""
from __future__ import annotations

from database.config import get_neo4j_driver

_ENTITY_LABELS = ("Artist", "Company", "AIModel", "Topic", "Case", "Law")
_MIN_TOKEN_LEN = 2  # 한 글자짜리 토큰은 노이즈 매칭이 너무 많아져서 제외


def _extract_tokens(query_text: str) -> list[str]:
    return [t for t in query_text.split() if len(t) >= _MIN_TOKEN_LEN]


def _find_related_document_ids(tokens: list[str], top_k_docs: int) -> list[str]:
    """토큰과 이름이 겹치는 엔티티에 연결된 Paper의 pg_document_id를,
    매칭된 엔티티 수(연결 강도) 내림차순으로 top_k_docs개 반환."""
    label_filter = " OR ".join(f"e:{label}" for label in _ENTITY_LABELS)
    cypher = f"""
        UNWIND $tokens AS token
        MATCH (e)
        WHERE ({label_filter}) AND toLower(e.name) CONTAINS toLower(token)
        MATCH (p:Paper)-[]->(e)
        RETURN p.pg_document_id AS document_id, count(DISTINCT e) AS match_count
        ORDER BY match_count DESC
        LIMIT $limit
    """
    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            rows = session.run(cypher, tokens=tokens, limit=top_k_docs)
            return [r["document_id"] for r in rows if r["document_id"]]
    finally:
        driver.close()


def graph_search(conn, query_text: str, top_k: int = 30) -> list[dict]:
    """
    conn: Postgres 커넥션 (매칭된 문서의 chunk를 가져오는 데 씀).
    query_text: 검색어(주제 문자열) — vector_search/keyword_search에 넘기는 것과 동일한 문자열.
    top_k: 반환할 chunk 후보 최대 개수.
    """
    tokens = _extract_tokens(query_text)
    if not tokens:
        return []

    try:
        document_ids = _find_related_document_ids(tokens, top_k_docs=top_k)
    except Exception as e:  # noqa: BLE001 — Neo4j 연결 실패해도 vector+keyword 검색은 계속 동작해야 함
        print(f"[graph_search] Neo4j 조회 실패, 그래프 검색 결과 없이 진행: {e}")
        return []

    if not document_ids:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, document_id, content
                FROM chunks
                WHERE document_id = ANY(%s::uuid[])
                ORDER BY document_id, chunk_index;
                """,
                (document_ids,),
            )
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001 — Neo4j 조회 실패와 동일한 이유로, 여기 실패해도
        # vector+keyword 검색까지 통째로 죽으면 안 됨 (search_context()가 이 예외를 그대로
        # 전파하면 그래프 검색만의 문제로 하이브리드 검색 전체가 실패하게 됨 — 실제로 겪었던 버그).
        print(f"[graph_search] chunks 조회 실패, 그래프 검색 결과 없이 진행: {e}")
        return []

    # 그래프 매칭 강도(document_ids 순서)를 그대로 rank로 씀 — 같은 문서의 chunk들은
    # 문서 단위로 매겨진 관련성을 공유(그래프 검색은 애초에 문서/엔티티 단위 신호라서 자연스러움).
    doc_rank = {doc_id: i + 1 for i, doc_id in enumerate(document_ids)}
    results = [
        {"chunk_id": r[0], "document_id": r[1], "content": r[2], "rank": doc_rank[r[1]]}
        for r in rows
    ]
    return results[:top_k]


if __name__ == "__main__":
    from database.config import get_connection

    with get_connection() as conn:
        hits = graph_search(conn, "Suno 저작권 침해")
        print(f"{len(hits)}건")
        for h in hits[:5]:
            print(f"- rank={h['rank']} doc={h['document_id']} {h['content'][:50]!r}")
