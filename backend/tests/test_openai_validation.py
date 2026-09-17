import pytest

from backend.app.schemas.llm import (
    GeneratedEvidence,
    GeneratedPaperContent,
    GeneratedSection,
)
from backend.app.schemas.rag import (
    RagContext,
    RagResult,
    Source,
)
from backend.app.services.openai_llm_service import (
    OpenAILLMService,
)


def make_rag_result() -> RagResult:
    return RagResult(
        contexts=[
            RagContext(
                chunk_id="chunk-1",
                document_id="doc-1",
                content="생성형 AI 음악 관련 근거 1",
                score=0.95,
            ),
            RagContext(
                chunk_id="chunk-2",
                document_id="doc-2",
                content="음성복제 관련 근거 2",
                score=0.91,
            ),
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

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
    )

    section = result.sections[0]

    assert section.citations == ["doc-1"]
    assert "[doc-1]" in section.content
    assert "[fake-source]" not in section.content


def test_duplicate_citations_are_removed():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="음성복제",
                content="음성복제 관련 내용입니다. [doc-2]",
                citations=[
                    "doc-2",
                    "[doc-2]",
                    "doc-2",
                ],
            ),
        ],
        conclusion="결론입니다.",
    )

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
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

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
    )

    assert len(result.sections) == 1
    assert result.sections[0].heading == "저작권"
    assert result.conclusion == "최종 결론입니다."


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
        OpenAILLMService._build_final_paper(
            generated=generated,
            rag_result=make_rag_result(),
        )


def test_references_are_removed_from_conclusion():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="저작권",
                content="본문 내용입니다. [doc-1]",
                citations=["doc-1"],
            ),
        ],
        conclusion=(
            "생성형 AI 음악에 대한 결론입니다.\n\n"
            "참고문헌\n"
            "- Fake Author. Fake Paper.\n"
            "- https://fake.example.com"
        ),
    )

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
    )

    assert (
        result.conclusion
        == "생성형 AI 음악에 대한 결론입니다."
    )

    assert "참고문헌" not in result.conclusion
    assert "Fake Author" not in result.conclusion

    assert len(result.references) == 2


def test_valid_evidence_creates_paper_citation():
    claim = "AI 음악의 저작권 문제가 논의되고 있습니다."

    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="저작권",
                content=f"{claim} [doc-1]",
                citations=["doc-1"],
                evidence=[
                    GeneratedEvidence(
                        claim_text=claim,
                        chunk_id="chunk-1",
                        document_id="doc-1",
                    )
                ],
            ),
        ],
        conclusion="결론입니다.",
    )

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
    )

    assert len(result.paper_citations) == 1

    citation = result.paper_citations[0]

    assert citation.section == "저작권"
    assert citation.chunk_id == "chunk-1"
    assert citation.document_id == "doc-1"
    assert citation.claim_text == claim
    assert citation.relevance_score == pytest.approx(
        0.95
    )


def test_invalid_chunk_document_pair_is_removed():
    claim = "AI 음악의 저작권 문제가 논의되고 있습니다."

    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="저작권",
                content=f"{claim} [doc-1]",
                citations=["doc-1"],
                evidence=[
                    GeneratedEvidence(
                        claim_text=claim,
                        chunk_id="chunk-1",
                        document_id="doc-2",
                    )
                ],
            ),
        ],
        conclusion="결론입니다.",
    )

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
    )

    assert result.paper_citations == []


def test_evidence_claim_must_exist_in_section_content():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="저작권",
                content="실제 본문 문장입니다. [doc-1]",
                citations=["doc-1"],
                evidence=[
                    GeneratedEvidence(
                        claim_text=(
                            "본문에 존재하지 않는 "
                            "별도의 주장입니다."
                        ),
                        chunk_id="chunk-1",
                        document_id="doc-1",
                    )
                ],
            ),
        ],
        conclusion="결론입니다.",
    )

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
    )

    assert result.paper_citations == []
def test_final_paper_over_4500_chars_is_rejected():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="초록입니다.",
        sections=[
            GeneratedSection(
                heading="본론",
                content="가" * 4500,
                citations=[],
            ),
        ],
        conclusion="결론입니다.",
    )

    with pytest.raises(
        ValueError,
        match="최종 논문 분량이 제한을 초과했습니다",
    ):
        OpenAILLMService._build_final_paper(
            generated=generated,
            rag_result=make_rag_result(),
            max_chars=4500,
        )


def test_final_paper_under_length_limit_is_allowed():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="연구 초록입니다.",
        sections=[
            GeneratedSection(
                heading="서론",
                content="연구 배경입니다.",
                citations=[],
            ),
            GeneratedSection(
                heading="본론",
                content="주요 논의입니다.",
                citations=[],
            ),
        ],
        conclusion="연구 결론입니다.",
    )

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
        max_chars=4500,
    )

    assert (
        OpenAILLMService._count_final_paper_chars(
            result
        )
        <= 4500
    )
def test_output_text_is_cleaned():
    generated = GeneratedPaperContent(
        title='"생성형 AI와 음악 창작&#x20;"',
        abstract="<p>초록&nbsp;내용입니다.</p>",
        sections=[
            GeneratedSection(
                heading="1. 서론",
                content=(
                    "1\n"
                    "<p>본문&nbsp;내용입니다.</p>"
                ),
                citations=[],
                evidence=[],
            ),
        ],
        conclusion=(
            "<div>결론&#x20;내용입니다.</div>"
        ),
    )

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
    )

    assert result.title == "생성형 AI와 음악 창작"
    assert result.abstract == "초록 내용입니다."

    assert (
        result.sections[0].content
        == "본문 내용입니다."
    )

    assert result.conclusion == "결론 내용입니다."

    assert "&#x20;" not in result.title
    assert "<p>" not in result.abstract
    assert "<div>" not in result.conclusion


def test_internal_generation_process_is_rejected():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="연구 초록입니다.",
        sections=[
            GeneratedSection(
                heading="서론",
                content=(
                    "Transformer 초안과 "
                    "RAG 검색 근거를 결합하여 "
                    "논문을 작성하였다."
                ),
                citations=[],
                evidence=[],
            ),
        ],
        conclusion="연구 결론입니다.",
    )

    with pytest.raises(
        ValueError,
        match="내부 구현 정보",
    ):
        OpenAILLMService._build_final_paper(
            generated=generated,
            rag_result=make_rag_result(),
        )
def test_generated_text_cleanup():
    generated = GeneratedPaperContent(
        title='"생성형 AI와 음악 창작&#x20;"',
        abstract=(
            "<p>생성형&nbsp;AI 음악 연구에 대한 "
            "초록입니다.</p>"
        ),
        sections=[
            GeneratedSection(
                heading="1. 서론",
                content=(
                    "1\n"
                    "<p>생성형&nbsp;AI 음악의 "
                    "저작권 쟁점을 검토한다.</p>"
                ),
                citations=[],
                evidence=[],
            ),
        ],
        conclusion=(
            "<div>연구의 결론&#x20;입니다.</div>"
        ),
    )

    result = OpenAILLMService._build_final_paper(
        generated=generated,
        rag_result=make_rag_result(),
    )

    assert (
        result.title
        == "생성형 AI와 음악 창작"
    )

    assert (
        result.abstract
        == "생성형 AI 음악 연구에 대한 초록입니다."
    )

    assert (
        result.sections[0].content
        == "생성형 AI 음악의 저작권 쟁점을 검토한다."
    )

    assert (
        result.conclusion
        == "연구의 결론 입니다."
    )

    assert "&#x20;" not in result.title
    assert "&nbsp;" not in result.abstract

    assert "<p>" not in result.abstract
    assert "<p>" not in result.sections[0].content
    assert "<div>" not in result.conclusion

    assert (
        not result.sections[0].content.startswith("1")
    )


def test_internal_generation_process_is_rejected():
    generated = GeneratedPaperContent(
        title="생성형 AI와 음악 창작",
        abstract="연구 초록입니다.",
        sections=[
            GeneratedSection(
                heading="서론",
                content=(
                    "Transformer 초안과 "
                    "RAG 검색 근거를 결합하여 "
                    "최종 논문을 작성하였다."
                ),
                citations=[],
                evidence=[],
            ),
        ],
        conclusion="연구 결론입니다.",
    )

    with pytest.raises(
        ValueError,
        match="내부 구현 정보",
    ):
        OpenAILLMService._build_final_paper(
            generated=generated,
            rag_result=make_rag_result(),
        )