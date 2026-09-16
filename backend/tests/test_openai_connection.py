import asyncio

from langchain_openai import ChatOpenAI

from backend.app.core.config import get_settings


async def main() -> None:
    settings = get_settings()

    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key.get_secret_value(),
        use_responses_api=True,
        reasoning_effort="none",
        max_tokens=64,
        timeout=30,
        max_retries=1,
    )

    response = await llm.ainvoke(
        "OpenAI API 연결 테스트입니다. "
        "다른 설명 없이 정확히 OPENAI_OK 만 출력하세요."
    )

    print()
    print("=" * 50)
    print("MODEL")
    print("=" * 50)
    print(settings.openai_model)

    print()
    print("=" * 50)
    print("RESPONSE")
    print("=" * 50)
    print(response.text)


if __name__ == "__main__":
    asyncio.run(main())