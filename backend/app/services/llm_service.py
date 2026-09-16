from uuid import uuid4

from backend.app.schemas.paper import (
    FinalPaper,
    PaperCitation,
    PaperSection,
)
from backend.app.schemas.rag import RagResult
from backend.app.schemas.transformer import TransformerDraft


class LLMService:
    async def refine(
        self,
        topic: str,
        rag_result: RagResult,
        draft: TransformerDraft,
        length: int,
    ) -> FinalPaper:
        source_ids = [
            source.source_id
            for source in rag_result.sources
        ]

        analysis_heading = "3. 주요 쟁점 분석"

        analysis_content = "\n\n".join(
            context.content
            for context in rag_result.contexts
        )

        analysis_citations: list[str] = []

        paper_citations: list[
            PaperCitation
        ] = []

        for context in rag_result.contexts:
            if (
                context.chunk_id is None
                or context.document_id is None
            ):
                continue

            document_id = str(
                context.document_id
            )

            if document_id not in source_ids:
                continue

            if document_id not in analysis_citations:
                analysis_citations.append(
                    document_id
                )

            paper_citations.append(
                PaperCitation(
                    section=analysis_heading,
                    chunk_id=str(
                        context.chunk_id
                    ),
                    document_id=document_id,
                    claim_text=context.content,
                    relevance_score=context.score,
                )
            )

        sections = [
            PaperSection(
                heading="1. 서론",
                content=draft.introduction,
                citations=source_ids[:1],
            ),
            PaperSection(
                heading="2. 생성형 AI와 음악 창작",
                content=draft.body,
                citations=source_ids,
            ),
            PaperSection(
                heading=analysis_heading,
                content=analysis_content,
                citations=analysis_citations,
            ),
        ]

        return FinalPaper(
            paper_id=str(uuid4()),
            title=draft.title,
            abstract=draft.abstract,
            sections=sections,
            conclusion=draft.conclusion,
            references=rag_result.sources,
            paper_citations=paper_citations,
        )