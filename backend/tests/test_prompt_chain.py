import asyncio

from backend.app.llm.chains.paper_chain import PaperPromptChain
from backend.app.mocks.rag_mock import search_context
from backend.app.mocks.transformer_mock import generate_draft


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

        # ---------------------------------------------------------
        # System Prompt
        # ---------------------------------------------------------

        assert "학술 논문" in system_content

        # 프로젝트 전체 주제 유지
        assert (
            "생성형 AI와 음악 창작"
            in system_content
        )

        # 사용자 세부 주제를 최우선으로 사용
        assert (
            "USER RESEARCH TOPIC"
            in system_content
        )

        # 실제 사실 근거와 Draft 역할 분리
        assert (
            "EVIDENCE CONTEXT"
            in system_content
        )

        assert "DRAFT" in system_content

        # provenance 연결 규칙
        assert "chunk_id" in system_content
        assert "document_id" in system_content

        # 내부 구현 내용을 최종 논문에
        # 노출하지 않도록 하는 규칙
        assert (
            "내부 구현"
            in system_content
        )

        # ---------------------------------------------------------
        # User Prompt
        # ---------------------------------------------------------

        # 실제 사용자 연구 주제
        assert topic in user_content

        # 프로젝트 전체 Domain
        assert (
            "생성형 AI와 음악 창작"
            in user_content
        )

        # Mock RAG source가 Prompt에 전달되는지 확인
        assert "SRC001" in user_content
        assert "SRC002" in user_content

        # 새 Prompt 입력 구조
        assert (
            "[EVIDENCE CONTEXT]"
            in user_content
        )

        assert "[DRAFT]" in user_content

        assert (
            "[USER RESEARCH TOPIC]"
            in user_content
        )

        assert (
            "[PROJECT DOMAIN]"
            in user_content
        )

        # 길이 제한 전달 확인
        assert "4500" in user_content

    asyncio.run(run_test())