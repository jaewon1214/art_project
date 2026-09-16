from pydantic import BaseModel, Field


class GeneratedEvidence(BaseModel):
    claim_text: str = Field(
        description=(
            "해당 근거가 뒷받침하는 본문 속 실제 문장. "
            "section content에 작성한 문장을 그대로 복사하며 "
            "citation 표기 자체는 포함하지 않는다."
        )
    )

    chunk_id: str = Field(
        description=(
            "해당 주장을 뒷받침하는 RAG CONTEXT의 "
            "chunk_id. 제공된 값만 사용할 수 있다."
        )
    )

    document_id: str = Field(
        description=(
            "해당 chunk가 속한 document_id. "
            "같은 RAG CONTEXT에 제공된 값만 사용할 수 있다."
        )
    )


class GeneratedSection(BaseModel):
    heading: str = Field(
        description=(
            "논문 본문 섹션 제목. "
            "결론은 포함하지 않는다."
        )
    )

    content: str = Field(
        description="해당 섹션의 학술적 본문"
    )

    citations: list[str] = Field(
        default_factory=list,
        description=(
            "해당 섹션에서 사용한 source_id 목록. "
            "제공된 source_id만 사용할 수 있다."
        ),
    )

    evidence: list[GeneratedEvidence] = Field(
        default_factory=list,
        description=(
            "본문의 사실적 주장과 실제 RAG Chunk 사이의 "
            "근거 연결 정보. "
            "chunk_id와 document_id는 제공된 Context의 "
            "조합만 사용할 수 있다."
        ),
    )


class GeneratedPaperContent(BaseModel):
    title: str = Field(
        description="최종 논문 제목"
    )

    abstract: str = Field(
        description="최종 논문 초록"
    )

    sections: list[GeneratedSection] = Field(
        description=(
            "서론, 본론, 주요 쟁점 분석 등 본문 섹션 목록. "
            "결론 섹션은 포함하지 않는다."
        )
    )

    conclusion: str = Field(
        description=(
            "최종 논문의 결론. "
            "sections와 별도로 작성한다."
        )
    )