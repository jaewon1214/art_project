"""
PostgreSQL FTS(tsvector) 기반 키워드 검색.

2026-09-16: 쿼리 텍스트도 chunks.content_tsv를 만들 때와 동일하게 한국어 형태소 분석을
거치도록 고침(tokenize_for_search) — content_tsv가 이제 원문이 아니라 형태소 분석된
content_tokenized 기준으로 생성되므로(chunker.py/schema.sql 참고), 쿼리 쪽도 똑같이
토큰화해야 "저작권을"(본문) vs "저작권"(쿼리) 같은 조사 차이로 매칭이 안 되는 문제가 안 생김.
양쪽 다 토큰화 안 하거나 양쪽 다 토큰화해야 맞아떨어지지, 한쪽만 하면 의미가 없음.

2026-09-22: plainto_tsquery(전체 문장) -> 토큰별 OR 결합으로 변경. plainto_tsquery는
넘겨받은 토큰을 전부 AND로 묶는데, topic이 리서치 주제형 문장(예: "생성형 AI 음악 플랫폼을
둘러싼 국내외 저작권 소송 비교")이면 형태소분석 후에도 토큰이 6~8개씩 나와서, 이 전부를
동시에 포함하는 청크는 현실적으로 존재하지 않아 매칭이 통째로 0건이 되는 문제가 실제 논문
생성에서 발견됨(diagnose_retrieval.py로 확인 — "국내외 소송 비교"/"음성복제" 두 토픽 모두
keyword=0건, "신탁·등록 기준"만 우연히 원문 표현과 거의 동일해서 AND 조건을 뚫고 50건 나옴).
토큰 각각을 plainto_tsquery로 개별 tsquery화한 뒤 ||(tsquery OR 연산자)로 결합해서 AND
요구를 없앰 — ts_rank는 매칭된 lexeme 밀도를 반영하므로, 여러 토큰이 겹치는 청크가 자연히
더 위로 랭킹되어 랭킹 품질 자체는 유지됨. 토큰마다 plainto_tsquery에 파라미터로 개별
전달하므로(문자열을 직접 이어붙이지 않음) 토큰에 특수문자가 섞여도 안전함.
"""
from __future__ import annotations

from rag.preprocessing.korean_tokenize import tokenize_for_search
from rag.retrieval.metadata_filter import build_filter


def keyword_search(conn, query_text: str, category: str | None = None, top_k: int = 50) -> list[dict]:
    """
    query_text와 매칭되는 chunk를 ts_rank 기준 top_k개 반환.
    반환: [{"chunk_id": ..., "document_id": ..., "content": ..., "document_type": ..., "rank": 1}, ...]
    (rank는 1부터, RRF용. document_type은 2026-09-21 추가 — vector_search.py와 동일한 이유,
    context_builder.py의 문서유형 다양성 선별 로직에 씀.)
    """
    filter_sql, filter_params = build_filter(category=category)

    # 형태소 분석 결과가 비면(예: 쿼리가 전부 특수문자/영문 약어뿐) 원문으로 폴백.
    tokenized_query = tokenize_for_search(query_text) or query_text
    tokens = tokenized_query.split()
    if not tokens:
        return []

    # 토큰 개수만큼 plainto_tsquery(%s)를 만들고 ||(OR)로 이어붙임 — 예: 토큰 3개면
    # "plainto_tsquery('simple', %s) || plainto_tsquery('simple', %s) || plainto_tsquery('simple', %s)".
    # 이 표현식을 ts_rank(ORDER BY)와 WHERE절(@@) 두 곳에서 각각 쓰므로, params에도
    # tokens를 두 번(각 자리에 한 번씩) 넣어야 함 — 기존 코드의 [tokenized_query, tokenized_query, ...]
    # 패턴과 동일한 이유.
    tsquery_expr = " || ".join(["plainto_tsquery('simple', %s)"] * len(tokens))

    sql = f"""
        SELECT c.id AS chunk_id, c.document_id, c.content, d.document_type,
               ROW_NUMBER() OVER (
                   ORDER BY ts_rank(c.content_tsv, {tsquery_expr}) DESC
               ) AS rnk
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.content_tsv @@ ({tsquery_expr}) {filter_sql}
        ORDER BY rnk
        LIMIT %s;
    """
    params = [*tokens, *tokens, *filter_params, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {"chunk_id": r[0], "document_id": r[1], "content": r[2], "document_type": r[3], "rank": r[4]}
        for r in rows
    ]
