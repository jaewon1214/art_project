import asyncio

from backend.app.core.config import get_settings
from backend.app.core.exceptions import PaperGenerationError
from backend.app.schemas.paper import FinalPaper
from backend.app.services.llm_service import LLMService
from backend.app.services.openai_llm_service import OpenAILLMService
from backend.app.services.rag_service import RagService
from backend.app.services.transformer_service import TransformerService


class PaperService:
    RAG_TIMEOUT = 30

    # 실제 Qwen2.5-1.5B + LoRA는 최초 모델 로딩과
    # 5개 섹션 생성에 시간이 걸릴 수 있으므로 여유 있게 설정한다.
    TRANSFORMER_TIMEOUT = 300

    LLM_TIMEOUT = 180

    def __init__(self) -> None:
        settings = get_settings()

        self.rag_service = RagService()
        self.transformer_service = TransformerService()

        if settings.backend_use_mock_llm:
            self.llm_service = LLMService()
        else:
            self.llm_service = OpenAILLMService()

    async def generate(
        self,
        topic: str,
        length: int,
        title: str | None = None,
    ) -> FinalPaper:
        try:
            rag_task = asyncio.wait_for(
                self.rag_service.search(topic),
                timeout=self.RAG_TIMEOUT,
            )

            transformer_task = asyncio.wait_for(
                self.transformer_service.generate(topic),
                timeout=self.TRANSFORMER_TIMEOUT,
            )

            rag_result, transformer_draft = await asyncio.gather(
                rag_task,
                transformer_task,
            )

        except TimeoutError as exc:
            raise PaperGenerationError(
                message=(
                    "RAG 또는 Transformer 처리 시간이 "
                    "초과되었습니다."
                ),
                stage="context_and_draft",
            ) from exc

        except Exception as exc:
            raise PaperGenerationError(
                message=(
                    "RAG 또는 Transformer 처리 중 "
                    "오류가 발생했습니다."
                ),
                stage="context_and_draft",
            ) from exc

        try:
            final_paper = await asyncio.wait_for(
                self.llm_service.refine(
                    topic=topic,
                    rag_result=rag_result,
                    draft=transformer_draft,
                    length=length,
                    forced_title=title,
                ),
                timeout=self.LLM_TIMEOUT,
            )

        except TimeoutError as exc:
            raise PaperGenerationError(
                message="LLM 처리 시간이 초과되었습니다.",
                stage="llm_refinement",
            ) from exc

        except Exception as exc:
            raise PaperGenerationError(
                message="LLM 논문 정제 중 오류가 발생했습니다.",
                stage="llm_refinement",
            ) from exc

        return final_paper
