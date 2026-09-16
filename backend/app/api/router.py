from fastapi import APIRouter

from backend.app.api.routes.generate import router as generate_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.search import router as search_router


api_router = APIRouter()

api_router.include_router(
    health_router,
    tags=["Health"],
)

api_router.include_router(
    search_router,
    tags=["RAG"],
)

api_router.include_router(
    generate_router,
    tags=["Paper"],
)