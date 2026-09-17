from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Source(BaseModel):
    source_id: str
    title: str
    url: str

    publisher: str | None = None
    author: str | None = None
    published_at: date | None = None
    category: str | None = None


class RagContext(BaseModel):
    """
    RAG 검색 결과의 개별 Chunk.

    chunk_id / document_id를 유지해야
    최종 논문 생성 이후에도 어떤 근거 Chunk를
    사용했는지 추적할 수 있다.
    """

    chunk_id: str | None = None
    document_id: str | None = None

    content: str

    score: float | None = None


class RagResult(BaseModel):
    contexts: list[RagContext] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)

    @field_validator("contexts", mode="before")
    @classmethod
    def normalize_legacy_contexts(
        cls,
        value: Any,
    ) -> Any:
        """
        기존 Mock RAG가 list[str]을 반환하더라도
        Backend 테스트가 깨지지 않도록 호환성을 유지한다.

        실제 RAG에서는 dict 형태의
        chunk_id / document_id / content / score를 그대로 사용한다.
        """

        if value is None:
            return []

        if not isinstance(value, list):
            return value

        normalized: list[Any] = []

        for context in value:
            if isinstance(context, str):
                normalized.append(
                    {
                        "content": context,
                    }
                )
            else:
                normalized.append(context)

        return normalized