from typing import Literal

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    input_type: Literal["topic", "title"] = Field(
        default="topic",
        description=(
            "topic이면 입력을 연구 주제로 사용하고, "
            "title이면 입력값을 최종 논문 제목으로 그대로 사용합니다."
        ),
    )

    topic: str = Field(
        ...,
        min_length=3,
        max_length=500,
        examples=["생성형 AI 음악의 음성복제와 저작권"],
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