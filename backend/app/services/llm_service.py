from uuid import uuid4

from backend.app.schemas.paper import FinalPaper, PaperSection
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
                heading="3. 주요 쟁점 분석",
                content="\n\n".join(rag_result.contexts),
                citations=source_ids,
            ),
        ]

        return FinalPaper(
            paper_id=str(uuid4()),
            title=draft.title,
            abstract=draft.abstract,
            sections=sections,
            conclusion=draft.conclusion,
            references=rag_result.sources,
        )