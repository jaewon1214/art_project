import asyncio

from backend.app.core.config import get_settings
from backend.app.mocks.transformer_mock import (
    generate_draft as generate_mock_draft,
)
from backend.app.schemas.transformer import TransformerDraft


class TransformerService:
    async def generate(
        self,
        topic: str,
    ) -> TransformerDraft:
        settings = get_settings()

        if settings.backend_use_mock_transformer:
            return await generate_mock_draft(topic)

        raw_draft = await asyncio.to_thread(
            self._generate_real_draft,
            topic,
        )

        return TransformerDraft.model_validate(
            raw_draft
        )

    @staticmethod
    def _generate_real_draft(
        topic: str,
    ) -> dict:
        # 실제 Transformer는 torch / transformers / peft 등을
        # import하므로 Mock 모드에서는 이 import 자체를 하지 않는다.
        from paper_generator.generator import (
            generate_draft,
        )

        return generate_draft(topic)
