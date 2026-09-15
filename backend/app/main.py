from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.router import api_router
from backend.app.core.config import get_settings
from backend.app.core.exceptions import PaperGenerationError


settings = get_settings()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "RAG + Transformer + LangChain + LLM 기반 "
        "생성형 AI 음악 연구 논문 생성 API"
    ),
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PaperGenerationError)
async def paper_generation_exception_handler(
    request: Request,
    exc: PaperGenerationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": exc.message,
            "stage": exc.stage,
        },
    )


app.include_router(
    api_router,
    prefix="/api/v1",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
    }