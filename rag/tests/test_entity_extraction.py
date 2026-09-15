"""
entity_extraction의 순수 로직만 테스트 (LLM/DB 호출 없음) — extractor._parse_response()가
관련성 판정 + 엔티티/관계를 안전하게 파싱/필터링하는지, sync.normalize_name()이 기대대로
동작하는지 확인.
"""
import json

from rag.entity_extraction.extractor import _parse_response, _strip_code_fence
from rag.entity_extraction.sync import normalize_name


def test_strip_code_fence():
    raw = "```json\n{\"entities\": [], \"relations\": []}\n```"
    assert _strip_code_fence(raw) == '{"entities": [], "relations": []}'


def test_strip_code_fence_no_fence_passthrough():
    raw = '{"entities": [], "relations": []}'
    assert _strip_code_fence(raw) == raw


def test_parse_response_relevant_filters_unknown_types():
    raw = json.dumps(
        {
            "is_relevant": True,
            "relevance_reason": "Suno 저작권 이슈를 다룸",
            "entities": [
                {"name": "Suno", "entity_type": "AIModel"},
                {"name": "이상한개체", "entity_type": "NotAType"},
            ],
            "relations": [
                {"entity_name": "Suno", "entity_type": "AIModel", "relation_type": "DISCUSSES", "confidence": 0.9},
                {"entity_name": "X", "entity_type": "AIModel", "relation_type": "NOT_A_RELATION"},
            ],
        }
    )
    parsed = _parse_response(raw)
    assert parsed["is_relevant"] is True
    assert parsed["entities"] == [{"name": "Suno", "entity_type": "AIModel"}]
    assert len(parsed["relations"]) == 1
    assert parsed["relations"][0]["relation_type"] == "DISCUSSES"


def test_parse_response_irrelevant_document():
    raw = json.dumps(
        {
            "is_relevant": False,
            "relevance_reason": "AI 주식 시황 기사라 주제와 무관",
            "entities": [],
            "relations": [],
        }
    )
    parsed = _parse_response(raw)
    assert parsed["is_relevant"] is False
    assert parsed["entities"] == []


def test_parse_response_malformed_json_defaults_to_irrelevant():
    """파싱 실패 시 잘못 저장하는 것보다 안전하게 '관련 없음' 처리해야 함."""
    parsed = _parse_response("이건 JSON이 아님")
    assert parsed["is_relevant"] is False
    assert parsed["entities"] == []
    assert parsed["relations"] == []


def test_normalize_name():
    assert normalize_name("  Suno  ") == "suno"
    assert normalize_name("하이브 Entertainment") == "하이브_entertainment"
