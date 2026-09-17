from datetime import date

from pydantic import BaseModel, Field


class Source(BaseModel):
    source_id: str
    title: str
    url: str

    publisher: str | None = None
    author: str | None = None
    published_at: date | None = None
    category: str | None = None


class RagResult(BaseModel):
    contexts: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)