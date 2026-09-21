from fastapi import APIRouter

from backend.app.schemas.paper import FinalPaper
from backend.app.schemas.request import GenerateRequest
from backend.app.services.paper_service import PaperService


router = APIRouter()

paper_service = PaperService()


@router.post(
    "/generate",
    response_model=FinalPaper,
)
async def generate(
    request: GenerateRequest,
) -> FinalPaper:
    return await paper_service.generate(
        topic=request.topic,
        length=request.length,
        input_type=request.input_type,
    )