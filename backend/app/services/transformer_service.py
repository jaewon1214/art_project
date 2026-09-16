from backend.app.mocks.transformer_mock import generate_draft
from backend.app.schemas.transformer import TransformerDraft


class TransformerService:
    async def generate(self, topic: str) -> TransformerDraft:
        return await generate_draft(topic)