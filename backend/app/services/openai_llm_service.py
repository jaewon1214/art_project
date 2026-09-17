import html
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

    # 최종 논문에 노출되면 안 되는
    # 명백한 "내부 생성 과정" 표현만 검사한다.
    #
    # Transformer라는 단어 자체 등은
    # 실제 연구 주제에서 사용될 가능성이 있으므로
    # 단순 단어 하나만으로 차단하지 않는다.
    INTERNAL_LEAK_PATTERNS = (
        (
            "RAG 내부 처리 표현",
            re.compile(
                r"\bRAG\b\s*(?:검색|근거|자료|시스템|"
                r"context|컨텍스트)",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "Transformer 초안 표현",
            re.compile(
                r"\bTransformer\b\s*(?:초안|Draft)",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "LLM 내부 처리 표현",
            re.compile(
                r"\bLLM\b\s*(?:결과|정제|생성|처리|검증)",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "내부 provenance 식별자",
            re.compile(
                r"\b(?:chunk_id|document_id|source_id)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "Backend 내부 표현",
            re.compile(
                r"\bbackend\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "내부 파이프라인 표현",
            re.compile(
                r"(?:검색|생성|retrieval)\s*"
                r"(?:파이프라인|pipeline)",
                flags=re.IGNORECASE,
            ),
        ),
    )

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
        # 사용자가 더 작은 값을 요청하면
        # 해당 값을 최종 제한으로 사용한다.
        effective_length = min(
            max(length, 1),
            self.MAX_FINAL_PAPER_CHARS,
        )

        prompt_value = (
            await self.prompt_chain.build_prompt(
                topic=topic,
                length=effective_length,
                rag_result=rag_result,
                draft=draft,
            )
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
        섹션 제목 비교용 정규화.

        다음을 같은 heading으로 취급한다.

        1. 서론
        서론
        """

        cleaned = heading.strip()

        cleaned = re.sub(
            r"^\s*\d+\s*[.)．]?\s*",
            "",
            cleaned,
        )

        return "".join(
            cleaned.lower().split()
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
        claim_text와 section content를
        비교하기 위한 공백 정규화.
        """

        return re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

    @classmethod
    def _clean_generated_text(
        cls,
        text: str,
    ) -> str:
        """
        LLM 출력에 남을 수 있는 표현을 정리한다.

        처리:
        - HTML entity decode
        - HTML tag 제거
        - Markdown code fence 제거
        - zero-width 문자 제거
        - 단독 section 번호 제거
        - 공백 정리
        - 과도한 빈 줄 정리

        citation 자체는 여기서 건드리지 않는다.
        """

        if not text:
            return ""

        cleaned = html.unescape(
            str(text)
        )

        # HTML entity decode 이후 생성될 수 있는
        # non-breaking space 정리
        cleaned = cleaned.replace(
            "\xa0",
            " ",
        )

        # Zero-width / BOM
        cleaned = (
            cleaned
            .replace("\u200b", "")
            .replace("\ufeff", "")
        )

        # Markdown code fence
        cleaned = re.sub(
            r"```(?:[a-zA-Z0-9_+\-]+)?",
            "",
            cleaned,
        )

        # HTML tag
        cleaned = re.sub(
            r"<[^>]+>",
            "",
            cleaned,
        )

        # 다음처럼 숫자만 존재하는 독립 줄 제거:
        #
        # 1
        # 2
        # 3.
        # 4)
        cleaned = re.sub(
            r"(?m)^[ \t]*\d+[.)]?[ \t]*$",
            "",
            cleaned,
        )

        # 줄 내부 연속 공백 정리
        cleaned = re.sub(
            r"[^\S\r\n]+",
            " ",
            cleaned,
        )

        # 줄 앞뒤 공백 정리
        cleaned = re.sub(
            r"[ \t]*\n[ \t]*",
            "\n",
            cleaned,
        )

        # 과도한 빈 줄
        cleaned = re.sub(
            r"\n{3,}",
            "\n\n",
            cleaned,
        )

        return cleaned.strip()

    @classmethod
    def _remove_repeated_heading(
        cls,
        heading: str,
        content: str,
    ) -> str:
        """
        structured output에서 section heading이
        content 첫 줄에 다시 들어간 경우 제거한다.

        예:

        heading:
            1. 서론

        content:
            1. 서론
            연구 배경은...

        -> content:
            연구 배경은...
        """

        if not content:
            return ""

        lines = content.splitlines()

        while (
            lines
            and not lines[0].strip()
        ):
            lines.pop(0)

        if not lines:
            return ""

        first_line = lines[0].strip()

        if (
            cls._normalize_heading(
                first_line
            )
            == cls._normalize_heading(
                heading
            )
        ):
            lines = lines[1:]

        return "\n".join(
            lines
        ).strip()

    @classmethod
    def _count_final_paper_chars(
        cls,
        paper: FinalPaper,
    ) -> int:
        """
        실제 논문 표시 영역 글자 수를 계산한다.

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
            parts.append(
                section.heading
            )
            parts.append(
                section.content
            )

        parts.append(
            paper.conclusion
        )

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
        Prompt를 LLM이 위반하더라도
        Backend에서 최대 분량을 최종 차단한다.
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
    def _validate_no_internal_leak(
        cls,
        paper: FinalPaper,
    ) -> None:
        """
        Prompt가 실패하더라도
        내부 구현 설명이 사용자에게 그대로
        반환되는 것을 Backend에서 차단한다.

        단순히 'Transformer' 같은 기술명이
        등장했다는 이유만으로 차단하지 않고,
        내부 생성 과정을 나타내는 명백한
        표현만 검사한다.
        """

        text_parts: list[
            tuple[str, str]
        ] = [
            (
                "title",
                paper.title,
            ),
            (
                "abstract",
                paper.abstract,
            ),
            (
                "conclusion",
                paper.conclusion,
            ),
        ]

        for index, section in enumerate(
            paper.sections,
            start=1,
        ):
            text_parts.append(
                (
                    f"section[{index}].heading",
                    section.heading,
                )
            )

            text_parts.append(
                (
                    f"section[{index}].content",
                    section.content,
                )
            )

        for location, text in text_parts:
            for (
                pattern_name,
                pattern,
            ) in cls.INTERNAL_LEAK_PATTERNS:
                if pattern.search(text):
                    raise ValueError(
                        "최종 논문에 내부 구현 정보가 "
                        "노출되었습니다: "
                        f"{pattern_name} / "
                        f"{location}"
                    )

    @classmethod
    def _sanitize_inline_citations(
        cls,
        content: str,
        valid_source_ids: set[str],
    ) -> str:
        """
        본문의 [source_id] 형식 citation 중
        실제 RAG source에 존재하지 않는 값을 제거한다.
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

        cleaned = cls._clean_generated_text(
            cleaned
        )

        return cleaned.strip()

    @classmethod
    def _sanitize_conclusion(
        cls,
        conclusion: str,
    ) -> str:
        """
        conclusion 뒤에 참고문헌을
        임의 생성한 경우 제거한다.

        참고문헌은 FinalPaper.references에서만
        관리한다.
        """

        cleaned = cls._clean_generated_text(
            conclusion
        )

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

        return cls._clean_generated_text(
            cleaned
        )

    @classmethod
    def _build_final_paper(
        cls,
        generated: GeneratedPaperContent,
        rag_result: RagResult,
        max_chars: int | None = None,
    ) -> FinalPaper:
        """
        OpenAI Structured Output을 검증하여
        FinalPaper 객체로 변환한다.

        처리 순서:
        1. 출력 텍스트 정제
        2. section 검증
        3. citation 검증
        4. evidence provenance 검증
        5. 내부 구현 정보 검증
        6. 최종 길이 검증
        """

        valid_source_ids = {
            source.source_id
            for source in rag_result.sources
        }

        # 실제 RAG에서 반환된
        # chunk_id + document_id 조합만 인정한다.
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
            heading = cls._clean_generated_text(
                section.heading
            )

            content = cls._clean_generated_text(
                section.content
            )

            if not heading or not content:
                continue

            normalized_heading = (
                cls._normalize_heading(
                    heading
                )
            )

            # 결론은 별도 conclusion 필드에서만 관리.
            # "4. 결론"도 normalize 후 "결론"이 된다.
            if normalized_heading in {
                "결론",
                "conclusion",
            }:
                continue

            # 같은 heading 중복 제거.
            if normalized_heading in seen_headings:
                continue

            seen_headings.add(
                normalized_heading
            )

            # content 첫 줄에 heading이 또 나온 경우 제거.
            content = cls._remove_repeated_heading(
                heading=heading,
                content=content,
            )

            if not content:
                continue

            valid_citations: list[str] = []

            # Structured Output citations 검증.
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

            # 본문 안의 [source_id] citation 검증.
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
                # section과 동일한 방식으로 정제해야
                # HTML entity 등이 있어도
                # claim containment 검증이 일치한다.
                claim_text = (
                    cls._clean_generated_text(
                        evidence.claim_text
                    )
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
                # chunk/document 조합은 제거.
                if context is None:
                    continue

                # 해당 document가 SOURCES에도
                # 존재하는 경우만 인정.
                if document_id not in valid_source_ids:
                    continue

                normalized_claim = (
                    cls._normalize_text(
                        claim_text
                    )
                )

                # claim_text는 반드시 최종 section에
                # 실제 존재하는 문장이어야 한다.
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

                # 유효한 Evidence가 존재하면
                # 해당 document도 section citation에 포함.
                if (
                    document_id
                    not in valid_citations
                ):
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

        title = (
            cls._clean_generated_text(
                generated.title
            )
            .strip()
            .strip("\"'“”‘’")
            .strip()
        )

        abstract = cls._clean_generated_text(
            generated.abstract
        )

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

        # Prompt만 믿지 않고 Backend에서도
        # 내부 구현 정보 노출을 최종 차단한다.
        cls._validate_no_internal_leak(
            final_paper
        )

        effective_max_chars = (
            cls.MAX_FINAL_PAPER_CHARS
            if max_chars is None
            else min(
                max(max_chars, 1),
                cls.MAX_FINAL_PAPER_CHARS,
            )
        )

        cls._validate_final_length(
            paper=final_paper,
            max_chars=effective_max_chars,
        )

        return final_paper