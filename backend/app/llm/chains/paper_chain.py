import json
from datetime import date, datetime

from langchain_core.prompt_values import ChatPromptValue

from backend.app.llm.prompts.paper_prompt import paper_prompt
from backend.app.schemas.rag import RagResult
from backend.app.schemas.transformer import TransformerDraft


class PaperPromptChain:
    @staticmethod
    def _serialize_date(
        value: date | datetime | str | None,
    ) -> str | None:
        if value is None:
            return None

        if isinstance(value, (date, datetime)):
            return value.isoformat()

        return str(value)

    def _format_rag_context(
        self,
        rag_result: RagResult,
    ) -> str:
        """
        최종 LLM이 각 근거의 provenance를 명확하게
        이해할 수 있도록 RAG Context를 구조화한다.

        핵심 연결:
        chunk_id
            ↓
        document_id
            ↓
        content
            ↓
        score
        """

        if not rag_result.contexts:
            return (
                "사용 가능한 근거 Context가 없습니다. "
                "구체적인 사실을 임의로 생성하지 마십시오."
            )

        context_blocks: list[str] = []

        for index, context in enumerate(
            rag_result.contexts,
            start=1,
        ):
            context_data = {
                "evidence_index": index,
                "chunk_id": (
                    str(context.chunk_id)
                    if context.chunk_id is not None
                    else None
                ),
                "document_id": (
                    str(context.document_id)
                    if context.document_id is not None
                    else None
                ),
                "score": context.score,
                "content": context.content,
            }

            context_blocks.append(
                json.dumps(
                    context_data,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

        return "\n\n".join(
            context_blocks
        )

    def _format_sources(
        self,
        rag_result: RagResult,
    ) -> str:
        """
        RAG가 실제로 반환한 Source만 전달한다.

        LLM은 이 목록에 존재하는 source_id 외에는
        새로운 출처를 생성할 수 없다.
        """

        if not rag_result.sources:
            return (
                "사용 가능한 출처가 없습니다. "
                "출처 정보를 임의로 생성하지 마십시오."
            )

        source_blocks: list[str] = []

        for source in rag_result.sources:
            source_data = {
                "source_id": source.source_id,
                "title": source.title,
                "url": source.url,
                "publisher": source.publisher,
                "author": source.author,
                "published_at": self._serialize_date(
                    source.published_at
                ),
                "category": source.category,
            }

            source_blocks.append(
                json.dumps(
                    source_data,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

        return "\n\n".join(
            source_blocks
        )

    @staticmethod
    def _format_transformer_draft(
        draft: TransformerDraft,
    ) -> str:
        """
        Transformer 결과는 구조 참고용으로만 전달한다.

        사실 근거가 아니라는 규칙은
        paper_prompt.py에서 강하게 제한한다.
        """

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
                "topic": topic.strip(),
                "length": length,
                "rag_context": (
                    self._format_rag_context(
                        rag_result
                    )
                ),
                "sources": (
                    self._format_sources(
                        rag_result
                    )
                ),
                "transformer_draft": (
                    self._format_transformer_draft(
                        draft
                    )
                ),
            }
        )