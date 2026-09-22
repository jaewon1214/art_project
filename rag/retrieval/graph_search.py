"""
Neo4j 기반 그래프 검색 — Vector/Keyword Search랑 짝을 이루는 세 번째 검색 경로.

loader.py는 Postgres -> Neo4j로 "쓰는" 쪽이고, 이 모듈은 반대로 Neo4j에서 "찾아 읽는" 쪽.

방식: query_text에서 뽑은 단어들과 이름이 겹치는 엔티티(Artist/Company/AIModel/Topic/Case/Law)를
Neo4j에서 찾고, 그 엔티티랑 연결된 Paper 노드(-> documents)를 가중치 점수로 랭킹한 뒤,
Postgres에서 그 문서들의 chunk를 전부 끌어와 후보로 반환한다.

2026-09-17: 랭킹 기준을 "매칭된 엔티티 개수"(count)에서 "관계 타입 x 엔티티 타입 가중치 합"으로
변경 — 예전엔 회사명을 여럿 스쳐 언급(MENTIONS)만 한 일반 기사가, 사건 하나를 정면으로 다룬
(DISCUSSES) 기사보다 매칭 엔티티 수가 많다는 이유로 더 높은 순위를 받는 문제가 있었음
(예: "Sony/Warner/Universal/Anthropic 등 업계 동향" 기사가, "Concord Music Group v. Anthropic"
사건 자체를 다룬 기사보다 위로 올라옴). 이제는 DISCUSSES(핵심 주제로 다룸)가 MENTIONS(단순 언급)
보다, Case 엔티티(구체적 사건명) 매칭이 다른 엔티티 타입 매칭보다 더 높은 가중치를 받아서,
쿼리의 사건명/당사자명이 정확히 걸리는 문서가 우선적으로 올라오게 함.

반환 형식은 vector_search/keyword_search랑 동일 — [{"chunk_id","document_id","content","rank"}] —
그래서 hybrid_rrf.reciprocal_rank_fusion()에 그대로 같이 넣을 수 있다.

Neo4j가 아직 설정 안 됐거나(연결 실패) 매칭되는 엔티티가 없으면 빈 리스트를 반환 — 그래프 신호
없이도 vector+keyword만으로 검색이 계속 동작해야 하므로(다른 검색 함수들과 동일한 방어적 설계).

2026-09-22: _extract_tokens()가 query_text를 그냥 공백 기준으로만 쪼개던 걸 keyword_search.py와
동일하게 tokenize_for_search() 기반으로 바꿈. Neo4j entities.name은 LLM이 뽑은 깨끗한 명사
(조사 없음, entity_extraction/extractor.py 참고)인데, 원문을 공백으로만 쪼개면 "신탁·등록"
"저작물의"처럼 조사/구두점이 그대로 붙은 토큰이 남아서 아래 Cypher의 `e.name CONTAINS token`
substring 매칭이 실패함(예: entity.name="신탁"이어도 token="신탁·등록"은 entity.name보다 길어서
아예 안 걸림). keyword_search.py에서 고친 "원문 vs 형태소분석 불일치"와 같은 계열의 문제 —
형태소분석 결과가 비면(쿼리가 영문/기호뿐인 경우 등) 기존처럼 원문 공백분리로 폴백.
"""
from __future__ import annotations

from database.config import get_neo4j_driver
from rag.preprocessing.korean_tokenize import tokenize_for_search

_ENTITY_LABELS = ("Artist", "Company", "AIModel", "Topic", "Case", "Law")
_MIN_TOKEN_LEN = 2  # 한 글자짜리 토큰은 노이즈 매칭이 너무 많아져서 제외


def _extract_tokens(query_text: str) -> list[str]:
    tokenized = tokenize_for_search(query_text)
    words = tokenized.split() if tokenized else query_text.split()
    return [t for t in words if len(t) >= _MIN_TOKEN_LEN]


# 관계 타입 가중치 — DISCUSSES(핵심 주제로 다룸)가 CITES(근거로 인용)보다, CITES가
# MENTIONS/RELATED_TO(단순 언급/일반 연관)보다 문서-엔티티 연결이 더 강함을 반영.
_RELATION_WEIGHT_CYPHER = (
    "CASE type(r) WHEN 'DISCUSSES' THEN 3 WHEN 'CITES' THEN 2 ELSE 1 END"
)
# 엔티티 타입 가중치 — 쿼리에 구체적 사건명(Case)이 들어있는 경우, 그 사건 자체를 다루는
# 문서가 회사/아티스트명만 겹치는 문서보다 훨씬 강하게 올라와야 하므로 Case를 특별 대우.
_ENTITY_WEIGHT_CYPHER = "CASE WHEN e:Case THEN 3 ELSE 1 END"


def _find_related_document_ids(tokens: list[str], top_k_docs: int) -> list[str]:
    """토큰과 이름이 겹치는 엔티티에 연결된 Paper의 pg_document_id를,
    (관계 타입 가중치 x 엔티티 타입 가중치) 합산 점수 내림차순으로 top_k_docs개 반환.

    WITH DISTINCT p, e, r로 (문서, 엔티티, 관계) 조합을 먼저 중복 제거하는 이유: 여러 토큰이
    같은 엔티티 이름에 동시에 매칭되면(예: "Concord"와 "Music"이 둘 다 "Concord Music Group"에
    CONTAINS 매칭) UNWIND 특성상 같은 (p,e,r) 행이 토큰 수만큼 중복돼서 점수가 부풀 수 있음."""
    label_filter = " OR ".join(f"e:{label}" for label in _ENTITY_LABELS)
    cypher = f"""
        UNWIND $tokens AS token
        MATCH (e)
        WHERE ({label_filter}) AND toLower(e.name) CONTAINS toLower(token)
        MATCH (p:Paper)-[r]->(e)
        WITH DISTINCT p, e, r
        WITH p, sum({_RELATION_WEIGHT_CYPHER} * {_ENTITY_WEIGHT_CYPHER}) AS score
        RETURN p.pg_document_id AS document_id, score
        ORDER BY score DESC
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
                SELECT c.id, c.document_id, c.content, d.document_type
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.document_id = ANY(%s::uuid[])
                ORDER BY c.document_id, c.chunk_index;
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
    # document_type은 2026-09-21 추가 — 기존엔 chunks 단독 조회라 documents JOIN이 없었는데,
    # 다양성 선별 로직에 필요해져서 다른 세 채널과 동일하게 documents를 JOIN함.
    doc_rank = {doc_id: i + 1 for i, doc_id in enumerate(document_ids)}
    results = [
        {"chunk_id": r[0], "document_id": r[1], "content": r[2], "document_type": r[3], "rank": doc_rank[r[1]]}
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
