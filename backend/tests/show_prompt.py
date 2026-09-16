import asyncio

from backend.app.llm.chains.paper_chain import PaperPromptChain
from backend.app.mocks.rag_mock import search_context
from backend.app.mocks.transformer_mock import generate_draft


async def main() -> None:
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

    print()
    print("=" * 80)
    print("SYSTEM PROMPT")
    print("=" * 80)
    print(messages[0].content)

    print()
    print("=" * 80)
    print("USER PROMPT")
    print("=" * 80)
    print(messages[1].content)


if __name__ == "__main__":
    asyncio.run(main())