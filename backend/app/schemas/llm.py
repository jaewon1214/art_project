from pydantic import BaseModel, Field


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