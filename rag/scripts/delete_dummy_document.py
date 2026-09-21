"""
2026-09-19 데이터 감사에서 발견된 더미/플레이스홀더 테스트 문서 1건을 삭제하는 일회성 스크립트.

대상: url = 'https://www.musicbusinessworldwide.com/sample-article'
      (id = 20fb333b-e709-4d10-bb1f-24c7250d239b, content = '(정제된 본문 예시 텍스트...)')
초기 개발/시연 단계에서 파이프라인 검증용으로 넣었던 예시 데이터가 실제 수집 데이터 사이에
섞여 남아있던 것 — 실제 뉴스 기사가 아니므로 검색 결과에 노이즈가 됨.

chunks / document_entities는 documents FK가 ON DELETE CASCADE라(schema.sql 참고) documents
행 삭제만으로 자동 정리됨. Neo4j 쪽은 엔티티 자체가 아니라 문서-엔티티 연결(document_entities)만
있으므로 별도 그래프 정리는 불필요(엔티티 노드 자체는 다른 문서에서도 참조될 수 있어 남겨둠).

⚠️ 2026-09-19 실행 중 발견: paper_citations.document_id는 ON DELETE RESTRICT라(schema.sql
참고, paper_citations는 조회 편의를 위한 비정규화 컬럼이라 CASCADE로 조용히 같이 지워지면
안 된다고 보고 일부러 RESTRICT로 막아둔 것) 이 더미 문서를 근거로 인용한 paper_citations
행이 있으면(더미 데이터라 초기 파이프라인 시연/테스트용 논문 초안이 이 문서를 인용했을 가능성)
documents 삭제가 FK 위반으로 막힘. 그런 인용 자체도 더미 문서를 근거로 한 것이라 내용이
없는(실제로는 존재하지 않는 근거) 테스트 인용이므로, documents 삭제 전에 이 문서를 가리키는
paper_citations 행만 먼저 지움(해당 citation이 속한 papers 행이나 그 논문의 다른 citation은
안 건드림 — 그 논문 자체가 테스트용인지는 이 스크립트가 판단할 정보가 없음).

url이 이미 없으면(이미 지워졌거나 다른 이유로 존재하지 않으면) 아무것도 안 하고 종료.

실행 (secondpj 루트에서):
    python -m rag.scripts.delete_dummy_document
"""
from __future__ import annotations

from rag import config

DUMMY_URL = "https://www.musicbusinessworldwide.com/sample-article"


def main() -> None:
    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, content FROM documents WHERE url = %s;", (DUMMY_URL,))
            row = cur.fetchone()

            if row is None:
                print(f"대상 없음(이미 삭제됐거나 존재하지 않음): {DUMMY_URL}")
                return

            doc_id, title, content = row
            print(f"삭제 대상: id={doc_id}, title={title!r}, content={content!r}")

            cur.execute(
                "SELECT id, paper_id, section, claim_text FROM paper_citations WHERE document_id = %s;",
                (doc_id,),
            )
            citing_rows = cur.fetchall()
            if citing_rows:
                print(f"이 문서를 인용하는 paper_citations {len(citing_rows)}건 먼저 삭제:")
                for cite_id, paper_id, section, claim_text in citing_rows:
                    preview = (claim_text or "")[:60].replace("\n", " ")
                    print(f"  - citation {cite_id} (paper_id={paper_id}, section={section}): {preview!r}")
                cur.execute("DELETE FROM paper_citations WHERE document_id = %s;", (doc_id,))

            cur.execute("DELETE FROM documents WHERE id = %s;", (doc_id,))
        conn.commit()
        print(f"삭제 완료: {doc_id} (chunks/document_entities는 CASCADE로 함께 정리됨)")


if __name__ == "__main__":
    main()
