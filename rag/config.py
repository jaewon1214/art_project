"""
RAG 파이프라인 전용 설정 (임베딩 / LLM 엔티티추출). rag/ 아래 모든 모듈이 여기서 가져다 씀.

DB 접속 정보(DB_*, NEO4J_*)는 이 파일 소관이 아니라 database/config.py가 단일 출처임 —
여기서는 기존 코드(`config.get_connection()` 등)가 그대로 돌아가게 재수출(re-export)만 함.
"""
import os

from dotenv import load_dotenv

from database.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER  # noqa: F401
from database.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER  # noqa: F401
from database.config import get_connection, get_neo4j_driver  # noqa: F401

load_dotenv()

# --- Embedding ------------------------------------------------------------
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "")  # 예: "openai" | "sentence-transformers"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")        # 예: "text-embedding-3-small"
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))   # database/init/01_schema.sql의 VECTOR(1536)과 반드시 일치
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")

# --- LLM 엔티티 추출 (rag/entity_extraction/) --------------------------------
# 문서에서 아티스트/회사/AI모델/이슈 등을 자동으로 뽑아 entities/document_entities에
# 저장하고 Neo4j까지 동기화하는 데 씀. 비워두면 rag/pipeline/ingest.py가 이 단계를 건너뜀.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")   # "openai" | "anthropic"
LLM_MODEL = os.getenv("LLM_MODEL", "")          # 예: "gpt-4o-mini" | "claude-haiku-4-5"
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
