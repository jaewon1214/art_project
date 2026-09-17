from pydantic import BaseModel, Field

from backend.app.schemas.rag import Source


class PaperCitation(BaseModel):
    """
    최종 논문의 주장과 실제 RAG Chunk 사이의
    근거 추적 정보.
    """

    section: str

    chunk_id: str

    document_id: str

    claim_text: str

    relevance_score: float | None = None


class PaperSection(BaseModel):
    heading: str

    content: str

    citations: list[str] = Field(
        default_factory=list
    )


class FinalPaper(BaseModel):
    paper_id: str

    title: str

    abstract: str

    sections: list[PaperSection]

    conclusion: str

    references: list[Source]

    paper_citations: list[PaperCitation] = Field(
        default_factory=list
    )