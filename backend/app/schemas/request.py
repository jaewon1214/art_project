from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    topic: str = Field(
        ...,
        min_length=3,
        max_length=500,
        examples=["생성형 AI 음악의 음성복제와 저작권"],
    )

    length: int = Field(
        default=5000,
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