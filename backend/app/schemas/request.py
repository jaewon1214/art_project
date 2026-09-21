from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=3,
        max_length=500,
        description=(
            "최종 논문에 그대로 사용할 제목입니다. "
            "생략하면 기존 방식처럼 제목을 자동 생성합니다."
        ),
        examples=["생성형 AI 음악의 음성복제와 저작권에 관한 연구"],
    )

    topic: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description=(
            "근거 검색, Transformer 초안 생성, "
            "최종 논문 내용 구성에 사용할 연구 주제입니다."
        ),
        examples=["AI 음성복제 기술과 음악 창작자의 권리 보호 문제"],
    )

    length: int = Field(
        default=4500,
        ge=1000,
        le=20000,
    )


class SearchRequest(BaseModel):
    topic: str = Field(
        ...,
        min_length=3,
        max_length=500,
        examples=["AI 작곡과 창작자성"],
    )
