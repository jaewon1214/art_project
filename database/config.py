"""
DB 접속 설정 (Postgres + Neo4j). collector/, rag/, database/ 어디서든
`from database.config import ...` 로 가져다 씀 — DB 관련 설정의 단일 출처.

로컬 Docker든 AWS RDS/EC2든 .env 값만 바꾸면 코드는 안 바뀌게 하기 위한 파일.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Postgres -------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "app")
DB_PASSWORD = os.getenv("DB_PASSWORD", "app_password")
DB_NAME = os.getenv("DB_NAME", "music_ai_papers")

# --- Neo4j ------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j_password")


def get_connection():
    """psycopg2 커넥션 하나 열어서 반환. 짧은 스크립트/테스트에서 바로 쓰기용."""
    import psycopg2

    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME
    )


def get_neo4j_driver():
    """neo4j 드라이버 인스턴스 반환. database/neo4j/loader.py 등에서 바로 가져다 쓰기용.

    사용 후 driver.close() 하거나 `with get_neo4j_driver() as driver:` 로 쓸 것.
    """
    from neo4j import GraphDatabase

    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
