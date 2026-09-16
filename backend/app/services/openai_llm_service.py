import re
from uuid import uuid4

from langchain_openai import ChatOpenAI

from backend.app.core.config import get_settings
from backend.app.llm.chains.paper_chain import PaperPromptChain
from backend.app.schemas.llm import GeneratedPaperContent
from backend.app.schemas.paper import FinalPaper, PaperSection
from backend.app.schemas.rag import RagResult
from backend.app.schemas.transformer import TransformerDraft


class OpenAILLMService:
    def __init__(self) -> None:
        settings = get_settings()

        if settings.backend_openai_api_key is None:
            raise RuntimeError(
                "BACKEND_OPENAI_API_KEY가 설정되어 있지 않습니다."
            )

        api_key = (
            settings.backend_openai_api_key
            .get_secret_value()
        )

        if not api_key.strip():
            raise RuntimeError(
                "BACKEND_OPENAI_API_KEY가 비어 있습니다."
            )

        self.prompt_chain = PaperPromptChain()

        self.llm = ChatOpenAI(
            model=settings.backend_openai_model,
            api_key=api_key,
            use_responses_api=True,
            reasoning_effort="none",
            timeout=60,
            max_retries=1,
        )

        self.structured_llm = (
            self.llm.with_structured_output(
                GeneratedPaperContent,
                method="json_schema",
            )
        )

    async def refine(
        self,
        topic: str,
        rag_result: RagResult,
        draft: TransformerDraft,
        length: int,
    ) -> FinalPaper:
        prompt_value = await self.prompt_chain.build_prompt(
            topic=topic,
            length=length,
            rag_result=rag_result,
            draft=draft,
        )

        generated = await self.structured_llm.ainvoke(
            prompt_value
        )

        if not isinstance(
            generated,
            GeneratedPaperContent,
        ):
            raise TypeError(
                "LLM이 예상한 GeneratedPaperContent "
                "형식을 반환하지 않았습니다."
            )

        return self._build_final_paper(
            generated=generated,
            rag_result=rag_result,
        )

    @staticmethod
    def _normalize_heading(
        heading: str,
    ) -> str:
        """
        섹션 제목 비교를 위해
        대소문자와 공백을 제거한다.
        """
        return "".join(
            heading.strip().lower().split()
        )

    @staticmethod
    def _normalize_citation_id(
        citation: str,
    ) -> str:
        """
        [doc-1], doc-1 등의 citation 표현을
        동일한 source_id 형식으로 변환한다.
        """
        return (
            citation
            .strip()
            .strip("[]")
            .strip()
        )

    @classmethod
    def _sanitize_inline_citations(
        cls,
        content: str,
        valid_source_ids: set[str],
    ) -> str:
        """
        본문의 [source_id] 형식 citation 중
        실제 RAG source에 존재하지 않는 citation을 제거한다.
        """

        pattern = re.compile(
            r"\[([^\[\]]+)\]"
        )

        def replace_citation(
            match: re.Match[str],
        ) -> str:
            citation_id = (
                cls._normalize_citation_id(
                    match.group(1)
                )
            )

            if citation_id in valid_source_ids:
                return f"[{citation_id}]"

            return ""

        cleaned = pattern.sub(
            replace_citation,
            content,
        )

        # 잘못된 citation 제거 후 생길 수 있는
        # 연속 공백을 하나로 정리한다.
        cleaned = re.sub(
            r"[ \t]{2,}",
            " ",
            cleaned,
        )

        return cleaned.strip()

    @staticmethod
    def _sanitize_conclusion(
        conclusion: str,
    ) -> str:
        """
        LLM이 conclusion 뒤에 참고문헌을 임의로
        생성하더라도 제거한다.

        참고문헌은 FinalPaper.references에서만 관리한다.
        """

        cleaned = conclusion.strip()

        bibliography_pattern = re.compile(
            r"\n\s*(?:"
            r"참고문헌"
            r"|참고\s*문헌"
            r"|references?"
            r"|bibliography"
            r")\s*:?\s*(?:\n|$)",
            flags=re.IGNORECASE,
        )

        match = bibliography_pattern.search(
            cleaned
        )

        if match:
            cleaned = cleaned[
                :match.start()
            ]

        return cleaned.strip()

    @classmethod
    def _build_final_paper(
        cls,
        generated: GeneratedPaperContent,
        rag_result: RagResult,
    ) -> FinalPaper:
        """
        OpenAI Structured Output을 검증하여
        최종 FinalPaper 객체로 변환한다.

        검증 내용:
        - 존재하지 않는 citation 제거
        - 본문 inline citation 검증
        - 동일 제목 섹션 중복 제거
        - sections 안의 결론 제거
        - 빈 섹션 제거
        - 제목/초록/결론 비어 있음 검증
        - conclusion에 생성된 참고문헌 제거
        """

        valid_source_ids = {
            source.source_id
            for source in rag_result.sources
        }

        validated_sections: list[
            PaperSection
        ] = []

        seen_headings: set[str] = set()

        for section in generated.sections:
            heading = section.heading.strip()
            content = section.content.strip()

            # 빈 섹션 제거
            if not heading or not content:
                continue

            normalized_heading = (
                cls._normalize_heading(
                    heading
                )
            )

            # 결론은 FinalPaper.conclusion에서만 관리
            if normalized_heading in {
                "결론",
                "conclusion",
            }:
                continue

            # 동일한 제목의 섹션 중복 방지
            if (
                normalized_heading
                in seen_headings
            ):
                continue

            seen_headings.add(
                normalized_heading
            )

            # structured output의 citations 검증
            valid_citations: list[str] = []

            for citation in section.citations:
                citation_id = (
                    cls._normalize_citation_id(
                        citation
                    )
                )

                if (
                    citation_id
                    in valid_source_ids
                    and citation_id
                    not in valid_citations
                ):
                    valid_citations.append(
                        citation_id
                    )

            # 본문 안 citation도 별도로 검증
            sanitized_content = (
                cls._sanitize_inline_citations(
                    content=content,
                    valid_source_ids=(
                        valid_source_ids
                    ),
                )
            )

            if not sanitized_content:
                continue

            validated_sections.append(
                PaperSection(
                    heading=heading,
                    content=sanitized_content,
                    citations=valid_citations,
                )
            )

        if not validated_sections:
            raise ValueError(
                "LLM 결과에 유효한 본문 섹션이 없습니다."
            )

        title = generated.title.strip()
        abstract = generated.abstract.strip()

        conclusion = (
            cls._sanitize_conclusion(
                generated.conclusion
            )
        )

        if not title:
            raise ValueError(
                "LLM 결과의 제목이 비어 있습니다."
            )

        if not abstract:
            raise ValueError(
                "LLM 결과의 초록이 비어 있습니다."
            )

        if not conclusion:
            raise ValueError(
                "LLM 결과의 결론이 비어 있습니다."
            )

        return FinalPaper(
            paper_id=str(uuid4()),
            title=title,
            abstract=abstract,
            sections=validated_sections,
            conclusion=conclusion,
            references=rag_result.sources,
        )