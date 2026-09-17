import asyncio
import json

from backend.app.mocks.rag_mock import search_context
from backend.app.mocks.transformer_mock import generate_draft
from backend.app.services.openai_llm_service import OpenAILLMService


async def main() -> None:
    topic = "생성형 AI 음악의 음성복제와 저작권"

    print("[1/4] Mock RAG 실행")

    rag_result = await search_context(topic)

    print(
        f"      contexts={len(rag_result.contexts)}, "
        f"sources={len(rag_result.sources)}"
    )

    print("[2/4] Mock Transformer 실행")

    draft = await generate_draft(topic)

    print(
        f"      draft title={draft.title}"
    )

    print("[3/4] OpenAI LLM 논문 정제")

    service = OpenAILLMService()

    final_paper = await service.refine(
        topic=topic,
        rag_result=rag_result,
        draft=draft,
        length=1500,
    )

    print("[4/4] Final Paper 생성 완료")

    print()
    print("=" * 80)
    print("FINAL PAPER")
    print("=" * 80)

    print(
        json.dumps(
            final_paper.model_dump(
                mode="json"
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())