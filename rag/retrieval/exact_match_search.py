"""
쿼리에 포함된 고유명사(사건명/회사명 등, 영문 대문자로 시작하는 단어열)를 뽑아서
content에 그 문자열이 그대로(대소문자 무시) 포함된 chunk를 찾는 네 번째 검색 경로.

vector_search(의미 유사도)/keyword_search(형태소 단위 매칭)/graph_search(엔티티 그래프)
셋 다 "정확히 이 이름이 언급됐는가"를 직접 보진 않음 — 특히 vector_search는 문장 전체를
하나의 임베딩으로 뭉개기 때문에 "Concord Music Group"처럼 쿼리에 박힌 고유명사 하나가
문서 전체의 의미적 유사도에 묻혀버릴 수 있고, keyword_search도 쿼리가 길면(연구주제형
문자열 등) AND 결합 특성상 고유명사 하나만으로는 못 끌어올림. 이 모듈은 "쿼리에 정확히
그 이름이 있고 문서에도 그 이름이 그대로 있으면 무조건 후보로 올린다"는 안전망 역할.

반환 형식은 vector_search/keyword_search/graph_search와 동일 —
[{"chunk_id", "document_id", "content", "rank"}] — 그대로 reciprocal_rank_fusion()에 넣을 수 있음.

Neo4j 엔티티 추출이 안 됐거나(그래프 검색이 못 잡는 경우) 아직 엔티티로 안 뽑힌 이름이어도
content 텍스트 자체에 문자열이 있으면 여기서 잡히므로 graph_search의 보완 채널로도 동작함.
"""
from __future__ import annotations

import re

from rag.retrieval.metadata_filter import build_filter

# 연속된 "대문자로 시작하는 단어"들을 고유명사 후보로 취급.
# 예: "Concord Music Group", "Anthropic", "ABKCO", "Universal Music Publishing".
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.'-]{1,}(?:\s+[A-Z][A-Za-z0-9&.'-]{1,})*\b")
_MIN_PHRASE_LEN = 3
# "v"/"vs"/"Inc" 등 단독으로 뽑히면 노이즈인 흔한 토큰은 후보에서 제외.
_STOPWORDS = {"v", "vs", "inc", "co", "ltd", "llc", "the", "a", "an", "of", "and"}


def _extract_proper_nouns(query_text: str) -> list[str]:
    """query_text에서 고유명사 후보 문자열 리스트를 중복 없이 뽑음(등장 순서 유지)."""
    candidates: list[str] = []
    seen: set[str] = set()
    for m in _PROPER_NOUN_RE.finditer(query_text):
        phrase = m.group().strip()
        if len(phrase) < _MIN_PHRASE_LEN or phrase.lower() in _STOPWORDS:
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(phrase)
    return candidates


def exact_match_search(conn, query_text: str, category: str | None = None, top_k: int = 30) -> list[dict]:
    """
    query_text에서 뽑은 고유명사 후보가 content에 그대로 포함된 chunk를 찾음.
    같은 chunk에 매칭되는 후보 문구가 많을수록(=더 구체적으로 일치할수록) 높은 순위(rank 1에 가까움).
    후보가 하나도 없으면(쿼리가 전부 한국어인 경우 등) 빈 리스트 반환 —
    vector/keyword/graph 검색과 동일하게 "있으면 쓰고 없으면 건너뛰는" 방어적 설계.
    """
    candidates = _extract_proper_nouns(query_text)
    if not candidates:
        return []

    filter_sql, filter_params = build_filter(category=category)
    like_clauses = " OR ".join("c.content ILIKE %s" for _ in candidates)
    score_terms = " + ".join("CASE WHEN c.content ILIKE %s THEN 1 ELSE 0 END" for _ in candidates)
    like_params = [f"%{c}%" for c in candidates]

    sql = f"""
        SELECT c.id AS chunk_id, c.document_id, c.content,
               ROW_NUMBER() OVER (ORDER BY ({score_terms}) DESC) AS rnk
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE ({like_clauses}) {filter_sql}
        ORDER BY rnk
        LIMIT %s;
    """
    # SQL 텍스트에 %s가 나오는 순서대로: score_terms(SELECT) -> like_clauses(WHERE) -> filter -> top_k
    params = [*like_params, *like_params, *filter_params, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {"chunk_id": r[0], "document_id": r[1], "content": r[2], "rank": r[3]}
        for r in rows
    ]


if __name__ == "__main__":
    from database.config import get_connection

    with get_connection() as conn:
        hits = exact_match_search(conn, "Concord Music Group 외 v. Anthropic 사건을 중심으로")
        print(f"{len(hits)}건")
        for h in hits[:5]:
            print(f"- rank={h['rank']} doc={h['document_id']} {h['content'][:50]!r}")
