import pytest

from backend.app.schemas.llm import (
    GeneratedPaperContent,
    GeneratedSection,
)
from backend.app.schemas.rag import (
    RagResult,
    Source,
)
from backend.app.services.openai_llm_service import (
    OpenAILLMService,
)


def make_rag_result() -> RagResult:
    return RagResult(
        contexts=[
            "생성형 AI 음악 관련 근거 1",
            "음성복제 관련 근거 2",
        ],
        sources=[
            Source(
                source_id="doc-1",
                title="AI Music Copyright",
                url="https://example.com/1",
            ),
            Source(
                source_id="doc-2",
                title="Voice Cloning",
                url="https://example.com/2",
            ),
        ],
    )


def test_invalid_citation_is_removed():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="저작권",
                content=(
                    "AI 음악 저작권에 관한 내용입니다. "
                    "[doc-1] [fake-source]"
                ),
                citations=[
                    "doc-1",
                    "fake-source",
                ],
            ),
        ],
        conclusion="결론입니다.",
    )

    result = (
        OpenAILLMService
        ._build_final_paper(
            generated=generated,
            rag_result=make_rag_result(),
        )
    )

    section = result.sections[0]

    assert section.citations == [
        "doc-1"
    ]

    assert "[doc-1]" in section.content

    assert (
        "[fake-source]"
        not in section.content
    )


def test_duplicate_citations_are_removed():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="음성복제",
                content=(
                    "음성복제 관련 내용입니다. "
                    "[doc-2]"
                ),
                citations=[
                    "doc-2",
                    "[doc-2]",
                    "doc-2",
                ],
            ),
        ],
        conclusion="결론입니다.",
    )

    result = (
        OpenAILLMService
        ._build_final_paper(
            generated=generated,
            rag_result=make_rag_result(),
        )
    )

    assert (
        result.sections[0].citations
        == ["doc-2"]
    )


def test_duplicate_and_conclusion_sections_are_removed():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="저작권",
                content="첫 번째 내용입니다.",
                citations=[],
            ),
            GeneratedSection(
                heading=" 저작권 ",
                content="중복된 내용입니다.",
                citations=[],
            ),
            GeneratedSection(
                heading="결론",
                content="중복 결론입니다.",
                citations=[],
            ),
        ],
        conclusion="최종 결론입니다.",
    )

    result = (
        OpenAILLMService
        ._build_final_paper(
            generated=generated,
            rag_result=make_rag_result(),
        )
    )

    assert len(result.sections) == 1

    assert (
        result.sections[0].heading
        == "저작권"
    )

    assert (
        result.conclusion
        == "최종 결론입니다."
    )


def test_no_valid_sections_raises_error():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="결론",
                content="결론 내용입니다.",
                citations=[],
            ),
        ],
        conclusion="최종 결론입니다.",
    )

    with pytest.raises(
        ValueError,
        match="유효한 본문 섹션",
    ):
        (
            OpenAILLMService
            ._build_final_paper(
                generated=generated,
                rag_result=make_rag_result(),
            )
        )


def test_references_are_removed_from_conclusion():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="저작권",
                content=(
                    "본문 내용입니다. "
                    "[doc-1]"
                ),
                citations=[
                    "doc-1"
                ],
            ),
        ],
        conclusion=(
            "생성형 AI 음악에 대한 결론입니다."
            "\n\n"
            "참고문헌\n"
            "- Fake Author. Fake Paper.\n"
            "- https://fake.example.com"
        ),
    )

    result = (
        OpenAILLMService
        ._build_final_paper(
            generated=generated,
            rag_result=make_rag_result(),
        )
    )

    assert (
        result.conclusion
        == "생성형 AI 음악에 대한 결론입니다."
    )

    assert (
        "참고문헌"
        not in result.conclusion
    )

    assert (
        "Fake Author"
        not in result.conclusion
    )

    assert len(result.references) == 2