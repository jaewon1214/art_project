from backend.app.schemas.transformer import TransformerDraft


async def generate_draft(topic: str) -> TransformerDraft:
    return TransformerDraft(
        title=f"{topic}에 관한 연구",
        abstract=(
            "본 연구는 생성형 인공지능 기술이 음악 창작 환경에 미치는 영향을 "
            "분석하고 저작권, 창작자성, 음성복제 및 AI 작곡과 관련된 주요 "
            "쟁점을 고찰한다."
        ),
        introduction=(
            "최근 생성형 인공지능 기술의 발전은 텍스트와 이미지 영역을 넘어 "
            "음악 창작 영역으로 빠르게 확대되고 있다. AI 작곡 및 음성복제 "
            "기술은 새로운 창작 가능성을 제공하는 동시에 기존 저작권 체계와 "
            "창작자의 개념에 새로운 문제를 제기하고 있다."
        ),
        body=(
            "생성형 AI 음악에서는 학습 데이터의 이용, 생성 결과물의 저작권 "
            "귀속, 인간 창작자의 기여 수준, 특정 가수의 음성을 모방하는 "
            "음성복제 기술 등이 주요 쟁점으로 논의될 수 있다."
        ),
        conclusion=(
            "생성형 AI를 음악 창작에 활용하기 위해서는 기술 발전을 장려하는 "
            "동시에 기존 창작자와 권리자의 권리를 보호할 수 있는 제도적 "
            "기준이 함께 마련될 필요가 있다."
        ),
    )