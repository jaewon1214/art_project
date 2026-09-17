import re
from uuid import uuid4

from langchain_openai import ChatOpenAI

from backend.app.core.config import get_settings
from backend.app.llm.chains.paper_chain import PaperPromptChain
from backend.app.schemas.llm import GeneratedPaperContent
from backend.app.schemas.paper import (
    FinalPaper,
    PaperCitation,
    PaperSection,
)
from backend.app.schemas.rag import RagResult
from backend.app.schemas.transformer import TransformerDraft


class OpenAILLMService:
    MAX_FINAL_PAPER_CHARS = 4500

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
        # 프로젝트 전체 최대 분량은 4500자.
        # 사용자가 더 작은 값을 요청한 경우에는 그 값을 우선한다.
        effective_length = min(
            length,
            self.MAX_FINAL_PAPER_CHARS,
        )

        prompt_value = await self.prompt_chain.build_prompt(
            topic=topic,
            length=effective_length,
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
            max_chars=effective_length,
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

    @staticmethod
    def _normalize_text(
        text: str,
    ) -> str:
        """
        claim_text가 실제 본문에 존재하는지
        비교하기 위한 공백 정규화.
        """

        return re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

    @classmethod
    def _count_final_paper_chars(
        cls,
        paper: FinalPaper,
    ) -> int:
        """
        최종 논문의 실제 표시 영역 글자 수를 계산한다.

        포함:
        - title
        - abstract
        - section heading
        - section content
        - conclusion

        제외:
        - references
        - paper_citations
        - paper_id
        """

        parts: list[str] = [
            paper.title,
            paper.abstract,
        ]

        for section in paper.sections:
            parts.append(section.heading)
            parts.append(section.content)

        parts.append(paper.conclusion)

        return sum(
            len(part)
            for part in parts
        )

    @classmethod
    def _validate_final_length(
        cls,
        paper: FinalPaper,
        max_chars: int,
    ) -> None:
        """
        LLM이 Prompt의 분량 지시를 어겼더라도
        Backend에서 최종적으로 초과 결과를 차단한다.
        """

        if max_chars <= 0:
            raise ValueError(
                "최종 논문 최대 글자 수는 "
                "1 이상이어야 합니다."
            )

        actual_chars = (
            cls._count_final_paper_chars(
                paper
            )
        )

        if actual_chars > max_chars:
            raise ValueError(
                "최종 논문 분량이 제한을 "
                f"초과했습니다: "
                f"{actual_chars}자 / "
                f"최대 {max_chars}자"
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
        max_chars: int | None = None,
    ) -> FinalPaper:
        """
        OpenAI Structured Output을 검증하여
        최종 FinalPaper 객체로 변환한다.

        검증 내용:
        - 존재하지 않는 source citation 제거
        - 본문 inline citation 검증
        - 존재하지 않는 chunk/document evidence 제거
        - claim_text가 실제 section 본문에 있는지 확인
        - 동일 evidence 중복 제거
        - RAG score를 provenance에 연결
        - 동일 제목 섹션 중복 제거
        - sections 안의 결론 제거
        - 빈 섹션 제거
        - 제목/초록/결론 비어 있음 검증
        - conclusion에 생성된 참고문헌 제거
        - 최종 논문 4500자 제한 검증
        """

        valid_source_ids = {
            source.source_id
            for source in rag_result.sources
        }

        context_lookup = {
            (
                str(context.chunk_id),
                str(context.document_id),
            ): context
            for context in rag_result.contexts
            if (
                context.chunk_id is not None
                and context.document_id is not None
            )
        }

        validated_sections: list[
            PaperSection
        ] = []

        paper_citations: list[
            PaperCitation
        ] = []

        seen_headings: set[str] = set()

        seen_evidence: set[
            tuple[str, str, str, str]
        ] = set()

        for section in generated.sections:
            heading = section.heading.strip()
            content = section.content.strip()

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

            # 같은 제목의 섹션 중복 방지
            if normalized_heading in seen_headings:
                continue

            seen_headings.add(
                normalized_heading
            )

            valid_citations: list[str] = []

            # structured output citation 검증
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

            # 본문 속 [source_id]도 검증
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

            normalized_content = (
                cls._normalize_text(
                    sanitized_content
                )
            )

            section_evidence: list[
                PaperCitation
            ] = []

            for evidence in section.evidence:
                claim_text = (
                    evidence.claim_text.strip()
                )

                chunk_id = (
                    evidence.chunk_id.strip()
                )

                document_id = (
                    evidence.document_id.strip()
                )

                if (
                    not claim_text
                    or not chunk_id
                    or not document_id
                ):
                    continue

                context = context_lookup.get(
                    (
                        chunk_id,
                        document_id,
                    )
                )

                # 실제 RAG에 없는
                # chunk/document 조합은 제거
                if context is None:
                    continue

                # document가 실제 SOURCES에도
                # 존재하는 경우만 provenance로 인정
                if document_id not in valid_source_ids:
                    continue

                normalized_claim = (
                    cls._normalize_text(
                        claim_text
                    )
                )

                # evidence에서 별도의 가짜 문장을
                # 만들어 넣는 것을 방지
                if (
                    not normalized_claim
                    or normalized_claim
                    not in normalized_content
                ):
                    continue

                evidence_key = (
                    normalized_heading,
                    chunk_id,
                    document_id,
                    normalized_claim,
                )

                if evidence_key in seen_evidence:
                    continue

                seen_evidence.add(
                    evidence_key
                )

                section_evidence.append(
                    PaperCitation(
                        section=heading,
                        chunk_id=chunk_id,
                        document_id=document_id,
                        claim_text=claim_text,
                        relevance_score=(
                            context.score
                        ),
                    )
                )

                # 정확한 evidence가 존재하면
                # 화면용 document citation에도 포함
                if document_id not in valid_citations:
                    valid_citations.append(
                        document_id
                    )

            validated_sections.append(
                PaperSection(
                    heading=heading,
                    content=sanitized_content,
                    citations=valid_citations,
                )
            )

            paper_citations.extend(
                section_evidence
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

        final_paper = FinalPaper(
            paper_id=str(uuid4()),
            title=title,
            abstract=abstract,
            sections=validated_sections,
            conclusion=conclusion,
            references=rag_result.sources,
            paper_citations=paper_citations,
        )

        effective_max_chars = (
            cls.MAX_FINAL_PAPER_CHARS
            if max_chars is None
            else min(
                max_chars,
                cls.MAX_FINAL_PAPER_CHARS,
            )
        )

        cls._validate_final_length(
            paper=final_paper,
            max_chars=effective_max_chars,
        )

        return final_paper

