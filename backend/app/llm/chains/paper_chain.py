import json

from langchain_core.prompt_values import ChatPromptValue

from backend.app.llm.prompts.paper_prompt import paper_prompt
from backend.app.schemas.rag import RagResult
from backend.app.schemas.transformer import TransformerDraft


class PaperPromptChain:
    def _format_rag_context(
        self,
        rag_result: RagResult,
    ) -> str:
        if not rag_result.contexts:
            return "검색된 RAG Context가 없습니다."

        context_blocks: list[str] = []

        for index, context in enumerate(
            rag_result.contexts,
            start=1,
        ):
            context_blocks.append(
                f"[CONTEXT {index}]\n{context}"
            )

        return "\n\n".join(context_blocks)

    def _format_sources(
        self,
        rag_result: RagResult,
    ) -> str:
        if not rag_result.sources:
            return "사용 가능한 출처가 없습니다."

        source_blocks: list[str] = []

        for source in rag_result.sources:
            source_data = {
                "source_id": source.source_id,
                "title": source.title,
                "url": source.url,
                "publisher": source.publisher,
                "published_at": (
                    source.published_at.isoformat()
                    if source.published_at
                    else None
                ),
            }

            source_blocks.append(
                json.dumps(
                    source_data,
                    ensure_ascii=False,
                )
            )

        return "\n".join(source_blocks)

    def _format_transformer_draft(
        self,
        draft: TransformerDraft,
    ) -> str:
        draft_data = {
            "title": draft.title,
            "abstract": draft.abstract,
            "introduction": draft.introduction,
            "body": draft.body,
            "conclusion": draft.conclusion,
        }

        return json.dumps(
            draft_data,
            ensure_ascii=False,
            indent=2,
        )

    async def build_prompt(
        self,
        topic: str,
        length: int,
        rag_result: RagResult,
        draft: TransformerDraft,
    ) -> ChatPromptValue:
        return await paper_prompt.ainvoke(
            {
                "topic": topic,
                "length": length,
                "rag_context": self._format_rag_context(
                    rag_result
                ),
                "sources": self._format_sources(
                    rag_result
                ),
                "transformer_draft": (
                    self._format_transformer_draft(
                        draft
                    )
                ),
            }
        )