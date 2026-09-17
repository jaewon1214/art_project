from uuid import uuid4

from backend.app.schemas.paper import (
    FinalPaper,
    PaperCitation,
    PaperSection,
)
from backend.app.schemas.rag import RagResult
from backend.app.schemas.transformer import TransformerDraft


class LLMService:
    """
    Backend 통합 테스트용 Mock LLM.

    실제 OpenAI LLM과 비슷한 형태의 FinalPaper를 반환하되
    외부 API 호출은 하지 않는다.
    """

    MAX_FINAL_PAPER_CHARS = 4500
    DEFAULT_TARGET_CHARS = 4200
    MIN_MOCK_PAPER_CHARS = 3600

    @staticmethod
    def _trim_text(
        text: str,
        limit: int,
    ) -> str:
        """
        최대 글자 수에 맞춰 텍스트를 줄인다.
        가능하면 문장 또는 문단 경계에서 자른다.
        """

        text = text.strip()

        if limit <= 0:
            return ""

        if len(text) <= limit:
            return text

        candidate = text[:limit].rstrip()

        # 문단 경계 우선
        paragraph_index = candidate.rfind("\n\n")

        if paragraph_index >= int(limit * 0.9):
            return candidate[
                :paragraph_index
            ].strip()

        # 한국어 문장 경계
        sentence_index = candidate.rfind("다.")

        if sentence_index >= int(limit * 0.85):
            return candidate[
                :sentence_index + 2
            ].strip()

        # 일반 마침표
        period_index = candidate.rfind(".")

        if period_index >= int(limit * 0.7):
            return candidate[
                :period_index + 1
            ].strip()

        return candidate

    @staticmethod
    def _count_paper_chars(
        title: str,
        abstract: str,
        sections: list[PaperSection],
        conclusion: str,
    ) -> int:
        """
        화면에 표시되는 논문 본문의 글자 수를 계산한다.

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

        total = (
            len(title)
            + len(abstract)
            + len(conclusion)
        )

        for section in sections:
            total += len(section.heading)
            total += len(section.content)

        return total

    @classmethod
    def _get_target_chars(
        cls,
        length: int,
    ) -> int:
        """
        요청 길이에 따른 Mock 논문의 목표 길이.

        length=4500이면 약 4200자를 목표로 한다.
        """

        hard_limit = min(
            max(length, 1),
            cls.MAX_FINAL_PAPER_CHARS,
        )

        if hard_limit >= 3500:
            return min(
                cls.DEFAULT_TARGET_CHARS,
                hard_limit,
            )

        return max(
            1,
            int(hard_limit * 0.9),
        )

    @staticmethod
    def _build_intro(
        topic: str,
        draft: TransformerDraft,
    ) -> str:
        return f"""
{draft.introduction}

본 연구는 '{topic}'을 단순한 기술 발전의 사례로만 보지 않고,
음악 창작 과정에서 인공지능이 담당하는 역할과 인간 창작자의
기여가 어떻게 구분될 수 있는지를 중심으로 살펴본다.
생성형 AI가 음악 제작에 활용될수록 창작 과정은 기존보다
복합적인 형태를 띠게 되며, 하나의 결과물이 만들어지는 과정에서
데이터, 모델, 사용자 입력, 편집과 선택 등 여러 요소가 함께
작용하게 된다.

따라서 생성형 AI 음악을 분석할 때에는 결과물 자체만 보는 것보다
그 결과물이 어떤 과정을 통해 만들어졌는지 함께 살펴볼 필요가
있다. 특히 저작권, 창작자성, 음성복제, AI 작곡이라는 쟁점은
서로 독립된 문제가 아니라 하나의 음악 생성 과정 안에서
연결되어 나타날 수 있다.

본 연구에서는 이러한 문제를 구분하여 검토하면서도 각 쟁점이
서로 어떤 영향을 주는지 함께 분석한다. Transformer가 생성한
초안은 전체적인 논문의 구조와 논지 형성에 활용하고, 구체적인
사실 판단은 RAG를 통해 검색된 근거를 중심으로 검토한다.
이를 통해 단순한 AI 생성 문장이 아니라 검색 근거를 바탕으로
논리를 정리한 논문 초안을 구성하는 것을 목적으로 한다.
""".strip()

    @staticmethod
    def _build_body(
        topic: str,
        draft: TransformerDraft,
    ) -> str:
        return f"""
{draft.body}

생성형 AI와 음악 창작의 관계를 검토하기 위해서는 먼저
AI가 창작 과정에서 수행하는 역할을 구분할 필요가 있다.
사용자가 주제나 분위기와 같은 조건을 입력하고 AI가 결과물을
생성하는 경우에도 최종 결과가 만들어지기까지는 여러 단계의
선택과 수정이 존재할 수 있다. 따라서 AI가 결과를 생성했다는
사실만으로 전체 창작 과정을 하나의 방식으로 설명하기보다는
사람과 시스템이 각각 어떤 역할을 수행했는지를 구체적으로
분석하는 방식이 필요하다.

저작권 문제에서는 학습 과정과 생성 결과물의 문제를 구분하여
살펴볼 필요가 있다. 학습 데이터의 이용과 최종 생성물의 권리
귀속은 서로 관련되어 있지만 동일한 질문은 아니다.
따라서 검색된 자료가 어느 단계의 문제를 설명하는지 구분하고,
한 단계에서 확인된 내용을 다른 단계의 사실처럼 확대하여
해석하지 않는 것이 중요하다.

창작자성의 문제에서는 인간이 결과물에 어느 정도 관여했는지가
핵심적인 분석 대상이 될 수 있다. 단순한 명령 입력뿐 아니라
생성 결과의 선택, 반복적인 수정, 편곡, 구조 변경과 같은
행위가 존재할 수 있기 때문에 인간의 창작적 기여를 분석할 때는
최종 파일만이 아니라 생성 과정 전체를 함께 보는 관점이
필요하다.

음성복제는 일반적인 AI 작곡과는 또 다른 문제를 제기한다.
음악의 멜로디나 구조를 생성하는 것과 특정 인물의 목소리와
유사한 음성을 생성하는 것은 분석 대상이 서로 다르기 때문이다.
따라서 음성복제 문제에서는 음악이라는 결과물뿐 아니라
목소리가 특정 개인을 식별하게 만드는 요소와 권리 보호 문제를
함께 검토해야 한다.

AI 작곡 역시 하나의 방식으로만 설명하기 어렵다.
AI가 아이디어를 제안하는 보조 도구로 사용될 수도 있고,
음악의 상당 부분을 자동으로 생성하는 방식으로 사용될 수도 있다.
이러한 차이는 인간의 기여를 평가하는 방식과 결과물에 대한
책임을 논의하는 방식에도 영향을 줄 수 있다.

결국 '{topic}'에 대한 분석에서는 기술의 사용 여부보다
구체적인 사용 방식과 창작 과정이 중요하다. 동일한 생성형 AI
기술을 사용하더라도 사람의 개입 수준, 데이터의 이용 방식,
결과물의 수정 과정에 따라 검토해야 할 쟁점은 달라질 수 있다.
따라서 논문에서는 개별 사례를 성급하게 일반화하기보다
RAG에서 확인된 근거와 Transformer가 제안한 논리 구조를
구분하여 사용하는 것이 필요하다.
""".strip()

    @staticmethod
    def _build_analysis_commentary(
        topic: str,
    ) -> str:
        return f"""
검색된 근거들을 종합하면 '{topic}'은 하나의 쟁점만으로
설명하기 어려운 복합적인 연구 주제라고 볼 수 있다.
저작권은 학습 데이터와 생성 결과물의 이용 문제를 중심으로,
창작자성은 인간과 AI의 기여 관계를 중심으로,
음성복제는 특정 개인의 음성과 유사한 결과를 생성하는 과정에서
발생하는 권리 문제를 중심으로 구분하여 살펴볼 필요가 있다.

이러한 구분은 각 문제를 완전히 분리하기 위한 것이 아니라
서로 다른 판단 기준을 혼동하지 않기 위한 것이다.
예를 들어 인간의 창작적 기여에 관한 논의가 곧바로 학습
데이터 이용 문제의 결론이 되는 것은 아니며, 음성복제 문제도
일반적인 음악 생성 문제와 동일한 기준만으로 설명하기 어렵다.

따라서 최종 논문에서는 검색된 자료가 실제로 뒷받침하는
범위까지만 사실적 주장을 사용하고, 그 밖의 부분은 분석적
논의로 명확하게 구분해야 한다. 특히 Transformer 초안에
구체적인 연도, 판례, 통계, 기관 또는 출처가 포함되어 있더라도
RAG 자료에서 확인되지 않는다면 최종 사실로 사용해서는 안 된다.

이와 같은 방식은 생성형 AI의 장점을 활용하면서도 생성 모델의
환각 가능성을 줄이는 데 목적이 있다. Transformer는 논문 형식과
논리 전개의 기반을 제공하고, RAG는 실제 검색 근거를 제공하며,
최종 LLM은 두 결과를 비교하여 문장을 정리하는 역할을 맡는다.
즉 각 구성 요소가 서로 다른 역할을 담당하도록 분리하는 것이
전체 시스템의 핵심이다.

또한 이러한 구조는 최종 결과의 신뢰성을 확인하는 과정에서도
의미가 있다. 생성된 문장과 검색 근거를 분리하여 관리하면
어떤 주장이 실제 자료에서 확인된 것인지 추적할 수 있고,
검증되지 않은 내용을 최종 논문에서 제외하기도 쉬워진다.
이는 단순히 긴 글을 생성하는 것보다 근거가 명확한 글을
생성하는 것이 중요하다는 점을 보여준다.

한편 RAG에서 제공되는 자료의 범위가 제한적이라면 최종 논문의
분석 범위 역시 제한될 수 있다. 따라서 근거가 부족한 부분을
임의의 사례나 수치로 보충하는 대신, 현재 확보된 자료가
어떤 쟁점을 설명할 수 있는지와 추가 검토가 필요한 부분을
구분하여 제시하는 것이 바람직하다.
""".strip()

    @staticmethod
    def _build_extra_analysis(
        topic: str,
    ) -> str:
        """
        Mock 결과가 지나치게 짧은 경우에만 추가하는
        일반적인 분석 문단.

        외부 판례, 통계, 연도, 기관명 등의
        검증되지 않은 사실은 넣지 않는다.
        """

        return f"""
'{topic}'에 관한 논의를 보다 안정적으로 구성하기 위해서는
기술의 기능과 사회적·법적 쟁점을 구분하여 살펴볼 필요가 있다.
생성형 AI가 음악을 만들 수 있다는 기술적 사실만으로
저작권이나 창작자성에 관한 판단이 자동으로 결정되는 것은 아니다.
창작 과정에서 사람이 수행한 역할과 AI가 수행한 역할을 구분하고,
그 과정에서 사용된 자료와 최종 결과물 사이의 관계를 함께
살펴보는 방식이 필요하다.

또한 동일한 생성형 AI 기술이라도 실제 활용 방식에 따라
검토해야 하는 문제는 달라질 수 있다. 아이디어를 얻기 위한
보조 도구로 사용하는 경우와 결과물 대부분을 자동으로 생성하는
경우에는 인간의 개입 정도와 창작 과정의 성격이 서로 다를 수
있다. 따라서 단순히 AI를 사용했다는 사실만으로 모든 결과를
동일하게 평가하기보다는 구체적인 생성 과정을 중심으로
분석하는 것이 더 적절하다.

근거 기반 논문 생성 시스템에서도 이러한 구분은 중요하다.
Transformer가 생성한 초안은 논문의 구조와 흐름을 만드는 데
유용하지만 구체적인 사실을 검증하는 자료로 사용할 수는 없다.
반대로 RAG가 제공하는 자료는 실제 검색된 근거를 제공하지만
그 자체만으로 완성된 논문의 구조를 만들지는 않는다.
따라서 두 결과의 역할을 분리한 뒤 최종 단계에서 결합하는
방식이 필요하다.

이 과정에서 최종 LLM은 단순히 두 입력을 합치는 역할보다
Transformer 초안의 주장을 RAG 근거와 비교하고, 확인되지 않는
내용을 제거하며, 남은 내용을 자연스러운 학술 문체로 정리하는
역할을 수행한다. 이러한 구조를 사용하면 결과 문장의 생성 과정과
근거 자료의 출처를 구분하여 확인할 수 있으며, 사용자가 필요할
경우 관련 자료를 다시 검토할 수 있는 기반도 마련된다.

결과적으로 생성형 AI 기반 논문 생성에서는 단순한 분량이나
문장의 자연스러움뿐 아니라 각 주장에 대한 검증 가능성이
중요하다. 충분한 근거가 존재하는 내용은 구체적으로 설명하고,
근거가 부족한 부분은 임의의 사실을 추가하기보다 분석 범위를
명확하게 제한하는 방식이 최종 결과의 신뢰성을 높이는 데
적절하다.
""".strip()

    @staticmethod
    def _build_conclusion(
        topic: str,
        draft: TransformerDraft,
    ) -> str:
        return f"""
{draft.conclusion}

종합하면 '{topic}'을 다룰 때에는 생성형 AI라는 기술 자체에
대한 평가보다 실제 창작 과정에서 인간과 AI가 어떤 방식으로
상호작용하는지를 구체적으로 살펴볼 필요가 있다. 저작권,
창작자성, 음성복제, AI 작곡은 서로 연결되어 있으면서도
각각 다른 판단 요소를 가지므로 하나의 기준만으로 모든 문제를
설명하는 것은 적절하지 않다.

따라서 최종 판단은 검증 가능한 자료를 중심으로 이루어져야 하며,
근거가 확인되지 않은 구체적 사실은 논문에서 배제할 필요가 있다.
본 시스템은 이러한 원칙에 따라 Transformer의 구조 생성 능력과
RAG의 근거 검색 기능을 결합하여 근거 기반의 논문 초안을
생성하는 것을 목표로 한다.
""".strip()

    @staticmethod
    def _select_evidence_contexts(
        rag_result: RagResult,
        source_ids: list[str],
        budget: int,
        section: str,
    ) -> tuple[
        list[str],
        list[str],
        list[PaperCitation],
    ]:
        """
        provenance가 깨지지 않도록 Context를 문장 중간에서
        자르지 않고, 예산 안에 들어오는 Context만 선택한다.
        """

        selected_contents: list[str] = []
        selected_citations: list[str] = []
        paper_citations: list[
            PaperCitation
        ] = []

        used_chars = 0

        for context in rag_result.contexts:
            content = context.content.strip()

            if not content:
                continue

            separator_chars = (
                2
                if selected_contents
                else 0
            )

            required_chars = (
                len(content)
                + separator_chars
            )

            if (
                used_chars + required_chars
                > budget
            ):
                continue

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

            selected_contents.append(
                content
            )

            used_chars += required_chars

            if (
                document_id
                not in selected_citations
            ):
                selected_citations.append(
                    document_id
                )

            paper_citations.append(
                PaperCitation(
                    section=section,
                    chunk_id=str(
                        context.chunk_id
                    ),
                    document_id=document_id,
                    claim_text=content,
                    relevance_score=context.score,
                )
            )

        return (
            selected_contents,
            selected_citations,
            paper_citations,
        )

    @classmethod
    def _ensure_minimum_length(
        cls,
        topic: str,
        title: str,
        abstract: str,
        sections: list[PaperSection],
        conclusion: str,
        hard_limit: int,
    ) -> list[PaperSection]:
        """
        Mock 결과가 지나치게 짧은 경우
        3번 분석 섹션에 일반적인 분석 내용을 보충한다.

        단:
        - 사용자가 요청한 최대 길이를 넘지 않는다.
        - 프로젝트 절대 최대 4500자를 넘지 않는다.
        - 기존 provenance 문장을 삭제하지 않는다.
        """

        if not sections:
            return sections

        minimum_target = min(
            cls.MIN_MOCK_PAPER_CHARS,
            hard_limit,
        )

        current_chars = cls._count_paper_chars(
            title=title,
            abstract=abstract,
            sections=sections,
            conclusion=conclusion,
        )

        if current_chars >= minimum_target:
            return sections

        available_chars = (
            hard_limit - current_chars
        )

        if available_chars <= 0:
            return sections

        extra_analysis = cls._build_extra_analysis(
            topic
        )

        # 현재 3340자 정도인 Mock에서는
        # 전체 보충 문단을 넣어 약 3600~4000자로 만든다.
        #
        # 이미 최대 분량에 가까운 경우에는
        # 사용 가능한 범위까지만 잘라서 추가한다.
        missing_chars = (
            minimum_target
            - current_chars
        )

        append_limit = min(
            missing_chars + 200,
            available_chars,
        )

        extra_analysis = cls._trim_text(
            extra_analysis,
            append_limit,
        )

        if not extra_analysis:
            return sections

        target_index = len(sections) - 1
        target_section = sections[
            target_index
        ]

        updated_content = (
            target_section.content.rstrip()
            + "\n\n"
            + extra_analysis
        )

        updated_section = PaperSection(
            heading=target_section.heading,
            content=updated_content,
            citations=target_section.citations,
        )

        updated_sections = list(sections)

        updated_sections[
            target_index
        ] = updated_section

        # 보충 후에도 혹시 최대 길이를 넘는 경우
        # 마지막으로 안전하게 잘라낸다.
        final_chars = cls._count_paper_chars(
            title=title,
            abstract=abstract,
            sections=updated_sections,
            conclusion=conclusion,
        )

        if final_chars > hard_limit:
            overflow = (
                final_chars
                - hard_limit
            )

            safe_limit = max(
                1,
                len(updated_content)
                - overflow
            )

            safe_content = cls._trim_text(
                updated_content,
                safe_limit,
            )

            updated_sections[
                target_index
            ] = PaperSection(
                heading=target_section.heading,
                content=safe_content,
                citations=target_section.citations,
            )

        return updated_sections

    async def refine(
        self,
        topic: str,
        rag_result: RagResult,
        draft: TransformerDraft,
        length: int,
    ) -> FinalPaper:
        hard_limit = min(
            max(length, 1),
            self.MAX_FINAL_PAPER_CHARS,
        )

        target_chars = (
            self._get_target_chars(
                hard_limit
            )
        )

        source_ids = [
            source.source_id
            for source in rag_result.sources
        ]

        title = draft.title.strip()

        headings = [
            "1. 서론",
            "2. 생성형 AI와 음악 창작",
            "3. 주요 쟁점 분석",
        ]

        fixed_chars = (
            len(title)
            + sum(
                len(heading)
                for heading in headings
            )
        )

        content_budget = max(
            target_chars - fixed_chars,
            1,
        )

        # 약 4200자 기준:
        # 초록       10%
        # 서론       23%
        # 본론       40%
        # 쟁점 분석  17%
        # 결론       10%
        abstract_budget = int(
            content_budget * 0.10
        )

        intro_budget = int(
            content_budget * 0.23
        )

        body_budget = int(
            content_budget * 0.40
        )

        analysis_budget = int(
            content_budget * 0.17
        )

        conclusion_budget = (
            content_budget
            - abstract_budget
            - intro_budget
            - body_budget
            - analysis_budget
        )

        abstract_candidate = f"""
{draft.abstract}

본 논문은 생성형 AI 음악을 둘러싼 저작권, 창작자성,
음성복제 및 AI 작곡 문제를 구분하여 검토하고,
Transformer 초안과 RAG 검색 근거를 결합하여
검증 가능한 논문 초안을 구성하는 것을 목적으로 한다.
""".strip()

        abstract = self._trim_text(
            abstract_candidate,
            abstract_budget,
        )

        introduction = self._trim_text(
            self._build_intro(
                topic=topic,
                draft=draft,
            ),
            intro_budget,
        )

        body = self._trim_text(
            self._build_body(
                topic=topic,
                draft=draft,
            ),
            body_budget,
        )

        analysis_heading = headings[2]

        # 분석 섹션 예산 중 약 55%까지
        # 실제 RAG 원문 근거에 사용한다.
        evidence_budget = int(
            analysis_budget * 0.55
        )

        (
            evidence_contents,
            analysis_citations,
            paper_citations,
        ) = self._select_evidence_contexts(
            rag_result=rag_result,
            source_ids=source_ids,
            budget=evidence_budget,
            section=analysis_heading,
        )

        analysis_parts = list(
            evidence_contents
        )

        analysis_parts.append(
            self._build_analysis_commentary(
                topic
            )
        )

        analysis_content = self._trim_text(
            "\n\n".join(
                analysis_parts
            ),
            analysis_budget,
        )

        conclusion = self._trim_text(
            self._build_conclusion(
                topic=topic,
                draft=draft,
            ),
            conclusion_budget,
        )

        sections = [
            PaperSection(
                heading=headings[0],
                content=introduction,
                citations=[],
            ),
            PaperSection(
                heading=headings[1],
                content=body,
                citations=[],
            ),
            PaperSection(
                heading=analysis_heading,
                content=analysis_content,
                citations=analysis_citations,
            ),
        ]

        # -------------------------------------------------
        # Mock 결과 최소 분량 보정
        # -------------------------------------------------
        sections = self._ensure_minimum_length(
            topic=topic,
            title=title,
            abstract=abstract,
            sections=sections,
            conclusion=conclusion,
            hard_limit=hard_limit,
        )

        return FinalPaper(
            paper_id=str(uuid4()),
            title=title,
            abstract=abstract,
            sections=sections,
            conclusion=conclusion,
            references=rag_result.sources,
            paper_citations=paper_citations,
        )