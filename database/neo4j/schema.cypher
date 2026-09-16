// =====================================================================
// "생성형 AI와 음악 창작" — Neo4j Knowledge Graph 스키마
// =====================================================================
// ※ STRETCH — 7일 시연 통과(초안 3편 생성)에는 필수 아님.
//   database/schema.sql의 MVP 5테이블(특히 papers/paper_citations)이 먼저.
//   시간 남으면 entities/document_entities 채운 뒤 이 파일 적용.
// 실행: cypher-shell -u neo4j -p <pw> -f schema.cypher
// 또는 Neo4j Browser에서 순서대로 실행
// =====================================================================

CREATE CONSTRAINT paper_key    IF NOT EXISTS FOR (n:Paper)    REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT artist_key   IF NOT EXISTS FOR (n:Artist)   REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT company_key  IF NOT EXISTS FOR (n:Company)  REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT aimodel_key  IF NOT EXISTS FOR (n:AIModel)  REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT topic_key    IF NOT EXISTS FOR (n:Topic)    REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT case_key     IF NOT EXISTS FOR (n:Case)     REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT law_key      IF NOT EXISTS FOR (n:Law)      REQUIRE n.key IS UNIQUE;

CREATE INDEX paper_title   IF NOT EXISTS FOR (n:Paper)   ON (n.title);
CREATE INDEX artist_name   IF NOT EXISTS FOR (n:Artist)  ON (n.name);
CREATE INDEX company_name  IF NOT EXISTS FOR (n:Company) ON (n.name);
CREATE INDEX aimodel_name  IF NOT EXISTS FOR (n:AIModel) ON (n.name);
CREATE INDEX topic_name    IF NOT EXISTS FOR (n:Topic)   ON (n.name);

// 노드 프로퍼티 관례:
// (:Paper {key, pg_document_id, title, published_at, category})
// (:Artist|Company|AIModel|Topic|Case|Law {key, pg_entity_id, name, ...})
//
// 관계: DISCUSSES · MENTIONS · DEVELOPS · RELATED_TO · CITES
// (Postgres document_entities.relation_type과 동일 어휘 — graph/loader.py 참고)
