import pytest

from backend.app.services.rag_service import RagService


def test_normalize_real_rag_result():
    raw_result = {
        "contexts": [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "content": "AI 음성복제와 저작권에 관한 내용입니다.",
                "score": 0.95,
            },
            {
                "chunk_id": "chunk-2",
                "document_id": "doc-2",
                "content": "생성형 AI 음악의 창작자성에 관한 내용입니다.",
                "score": 0.91,
            },
        ],
        "sources": [
            {
                "document_id": "doc-1",
                "title": "AI Voice Copyright",
                "url": "https://example.com/1",
                "author": "Author A",
                "published_at": "2025-11-10",
                "category": "음성복제",
            },
            {
                "document_id": "doc-2",
                "title": "AI Music Authorship",
                "url": "https://example.com/2",
                "author": "Author B",
                "published_at": "2025-12-01",
                "category": "창작자성",
            },
        ],
    }

    result = RagService._normalize_real_result(raw_result)

    assert len(result.contexts) == 2
    assert len(result.sources) == 2

    assert (
        result.contexts[0]
        == "AI 음성복제와 저작권에 관한 내용입니다."
    )

    assert result.sources[0].source_id == "doc-1"
    assert result.sources[0].title == "AI Voice Copyright"
    assert result.sources[0].author == "Author A"
    assert result.sources[0].category == "음성복제"


def test_normalize_real_rag_result_accepts_string_context():
    raw_result = {
        "contexts": [
            "문자열 형태의 기존 Context",
        ],
        "sources": [],
    }

    result = RagService._normalize_real_result(raw_result)

    assert result.contexts == [
        "문자열 형태의 기존 Context",
    ]


def test_normalize_real_rag_result_rejects_invalid_type():
    with pytest.raises(TypeError):
        RagService._normalize_real_result(
            ["잘못된 결과"]  # type: ignore[arg-type]
        )