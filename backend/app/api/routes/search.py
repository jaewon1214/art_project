from fastapi import APIRouter

from backend.app.schemas.rag import RagResult
from backend.app.schemas.request import SearchRequest
from backend.app.services.rag_service import RagService


router = APIRouter()

rag_service = RagService()


@router.post(
    "/search",
    response_model=RagResult,
)
async def search(
    request: SearchRequest,
) -> RagResult:
    return await rag_service.search(request.topic)