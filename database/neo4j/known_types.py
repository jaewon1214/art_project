"""
database/schema.sql · graph/schema.cypher와 반드시 같은 값을 써야 하는 허용 목록.
LLM 출력 검증 + Neo4j 라벨/관계타입으로 문자열을 그대로 Cypher에 꽂을 때(f-string) 안전하게
쓰기 위한 화이트리스트 — 여기 없는 값은 저장/적재를 거부한다.
"""
from __future__ import annotations

ENTITY_TYPES = {"Artist", "Company", "AIModel", "Topic", "Case", "Law"}

RELATION_TYPES = {"DISCUSSES", "MENTIONS", "DEVELOPS", "RELATED_TO", "CITES"}
