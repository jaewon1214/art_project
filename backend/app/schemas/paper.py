from pydantic import BaseModel, Field

from backend.app.schemas.rag import Source


class PaperSection(BaseModel):
    heading: str
    content: str
    citations: list[str] = Field(default_factory=list)


class FinalPaper(BaseModel):
    paper_id: str
    title: str
    abstract: str
    sections: list[PaperSection]
    conclusion: str
    references: list[Source]