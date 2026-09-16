import asyncio

from backend.app.llm.chains.paper_chain import PaperPromptChain
from backend.app.mocks.rag_mock import search_context
from backend.app.mocks.transformer_mock import generate_draft
from backend.app.schemas.rag import (
    RagContext,
    RagResult,
    Source,
)


def test_build_prompt() -> None:
    async def run_test() -> None:
        topic = "생성형 AI 음악의 음성복제와 저작권"

        rag_result = await search_context(topic)
        draft = await generate_draft(topic)

        chain = PaperPromptChain()

        prompt_value = await chain.build_prompt(
            topic=topic,
            length=4500,
            rag_result=rag_result,
            draft=draft,
        )

        messages = prompt_value.to_messages()

        assert len(messages) == 2

        system_content = str(
            messages[0].content
        )

        user_content = str(
            messages[1].content
        )

        assert "학술 논문" in system_content
        assert "Transformer Draft" in system_content

        assert topic in user_content

        assert "SRC001" in user_content
        assert "SRC002" in user_content

        assert "RAG CONTEXT" in user_content
        assert "TRANSFORMER DRAFT" in user_content

        assert "chunk_id" in system_content
        assert "document_id" in system_content

    asyncio.run(run_test())


def test_prompt_preserves_rag_trace_metadata() -> None:
    async def run_test() -> None:
        topic = "AI 음악 저작권"

        rag_result = RagResult(
            contexts=[
                RagContext(
                    chunk_id="chunk-001",
                    document_id="doc-001",
                    content="AI 음악 저작권 관련 근거입니다.",
                    score=0.97,
                )
            ],
            sources=[
                Source(
                    source_id="doc-001",
                    title="AI Music Copyright",
                    url="https://example.com/source",
                    author="Researcher",
                    category="저작권",
                )
            ],
        )

        draft = await generate_draft(topic)

        chain = PaperPromptChain()

        prompt_value = await chain.build_prompt(
            topic=topic,
            length=4500,
            rag_result=rag_result,
            draft=draft,
        )

        messages = prompt_value.to_messages()
        user_content = str(messages[1].content)

        assert "chunk-001" in user_content
        assert "doc-001" in user_content
        assert "AI 음악 저작권 관련 근거입니다." in user_content
        assert "0.97" in user_content
        assert "AI Music Copyright" in user_content
        assert '"category": "저작권"' in user_content

    asyncio.run(run_test())