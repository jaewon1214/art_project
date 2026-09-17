-- =====================================================================
-- seed.sql — 개발용 최소 샘플 데이터 (MVP 흐름 확인용) — v3 필드 반영
-- =====================================================================

INSERT INTO sources (name, source_type, base_url, trust_level) VALUES
    ('한국저작권위원회',           'policy',  'https://www.copyright.or.kr',              5),
    ('Music Business Worldwide', 'news',    'https://www.musicbusinessworldwide.com',   3),
    ('Billboard',                'news',    'https://www.billboard.com',                4);

INSERT INTO documents (source_id, title, content, url, author, category, document_type, published_at, language, content_hash)
VALUES (
    2,
    'AI 커버곡과 음성복제, 어디까지 저작권 침해인가',
    '(정제된 본문 예시 텍스트...)',
    'https://www.musicbusinessworldwide.com/sample-article',
    '기자 A',
    '음성복제',
    'news',
    '2025-11-10',
    'ko',
    'sample_hash_0001'
);

INSERT INTO chunks (document_id, chunk_index, content, token_count)
SELECT id, 0, '(첫 번째 청크 예시 텍스트...)', 120
FROM documents WHERE content_hash = 'sample_hash_0001';

-- LLM이 정제한 최종 초안 예시
INSERT INTO papers (topic, title, abstract, introduction, body, conclusion, status)
VALUES (
    '생성형 AI의 음성복제와 저작권 침해 문제',
    'AI 음성복제 시대의 저작권 재정립',
    '(초록 예시...)',
    '(서론 예시...)',
    '(본론 예시...)',
    '(결론 예시...)',
    'draft'
);

-- 근거 연결 예시: body 섹션 문장이 어떤 chunk를 근거로 썼는지 기록
INSERT INTO paper_citations (paper_id, section, chunk_id, document_id, claim_text, relevance_score)
SELECT p.id, 'body', c.id, c.document_id, 'AI 커버곡 확산이 저작권 침해 논쟁을 촉발했다.', 0.87
FROM papers p, chunks c
WHERE p.title = 'AI 음성복제 시대의 저작권 재정립'
  AND c.content = '(첫 번째 청크 예시 텍스트...)';

-- 검증 예시: 이 paper의 섹션별 citation 커버리지 확인 (schema.sql 하단 설명 참고)
-- SELECT s.section, COUNT(pc.id) AS citation_count
-- FROM unnest(ARRAY['introduction','body','conclusion']) AS s(section)
-- LEFT JOIN paper_citations pc
--        ON pc.paper_id = (SELECT id FROM papers WHERE title = 'AI 음성복제 시대의 저작권 재정립')
--       AND pc.section = s.section
-- GROUP BY s.section;
-- → introduction/conclusion은 citation_count = 0 (아직 근거 미연결) 이므로 최종본에서 제외해야 함
