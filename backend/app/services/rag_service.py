import asyncio
from typing import Any

from backend.app.core.config import get_settings
from backend.app.mocks.rag_mock import (
    search_context as mock_search_context,
)
from backend.app.schemas.rag import RagResult, Source


class RagService:
    async def search(self, topic: str) -> RagResult:
        settings = get_settings()

        # ---------------------------------------------------------
        # Backend 단독 개발/테스트용 Mock RAG
        # ---------------------------------------------------------
        if settings.backend_use_mock_rag:
            return await mock_search_context(topic)

        # ---------------------------------------------------------
        # 실제 RAG는 사용할 때만 import
        # 1번 담당 코드가 준비되지 않아도 Backend 단독 테스트 가능
        # ---------------------------------------------------------
        from rag.retrieval.context_builder import (
            search_context as real_search_context,
        )

        raw_result = await asyncio.to_thread(
            real_search_context,
            topic,
        )

        return self._normalize_real_result(raw_result)

    @staticmethod
    def _normalize_real_result(
        raw_result: dict[str, Any],
    ) -> RagResult:
        if not isinstance(raw_result, dict):
            raise TypeError(
                "RAG search_context() 결과가 dict 형식이 아닙니다."
            )

        raw_contexts = raw_result.get("contexts", [])
        raw_sources = raw_result.get("sources", [])

        contexts: list[str] = []

        for context in raw_contexts:
            if isinstance(context, str):
                contexts.append(context)
                continue

            if not isinstance(context, dict):
                continue

            content = context.get("content")

            if content:
                contexts.append(str(content))

        sources: list[Source] = []

        for source in raw_sources:
            if not isinstance(source, dict):
                continue

            document_id = source.get(
                "document_id",
                source.get("source_id"),
            )

            if document_id is None:
                continue

            sources.append(
                Source(
                    source_id=str(document_id),
                    title=str(source.get("title") or ""),
                    url=str(source.get("url") or ""),
                    publisher=source.get("publisher"),
                    author=source.get("author"),
                    published_at=source.get("published_at"),
                    category=source.get("category"),
                )
            )

        return RagResult(
            contexts=contexts,
            sources=sources,
        )