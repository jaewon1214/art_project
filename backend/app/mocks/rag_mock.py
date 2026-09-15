from backend.app.schemas.rag import RagResult, Source


async def search_context(topic: str) -> RagResult:
    return RagResult(
        contexts=[
            (
                f"연구 주제 '{topic}'와 관련하여 생성형 AI의 음악 활용은 "
                "저작권, 창작자성, 음성복제 등의 법적·윤리적 쟁점을 발생시킨다."
            ),
            (
                "AI 생성 음악의 저작권 논의에서는 인간 창작자의 개입 정도와 "
                "창작적 기여 수준이 중요한 쟁점이 될 수 있다."
            ),
            (
                "음성복제 기술은 특정 가수 또는 실연자의 목소리와 유사한 "
                "음성을 생성할 수 있기 때문에 권리 보호 문제가 발생할 수 있다."
            ),
            (
                "AI 작곡 기술은 기존 음악 데이터를 학습하여 새로운 음악을 "
                "생성할 수 있으며 학습 데이터 이용과 결과물의 권리 귀속 문제가 "
                "함께 논의될 수 있다."
            ),
        ],
        sources=[
            Source(
                source_id="SRC001",
                title="AI Music and Copyright",
                url="https://example.com/ai-music-copyright",
                publisher="Mock Research Institute",
                published_at="2026-08-01",
            ),
            Source(
                source_id="SRC002",
                title="Voice Cloning and Creator Rights",
                url="https://example.com/voice-cloning",
                publisher="Mock Policy Center",
                published_at="2026-08-15",
            ),
        ],
    )