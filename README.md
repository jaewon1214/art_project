# art-paper-project

"생성형 AI와 음악 창작" 논문 초안 AI-Agent 팀 프로젝트.

## 폴더 구조 & 담당

| 폴더 | 담당 | 브랜치 |
|---|---|---|
| `frontend/` | 프론트 | `feature/frontend` |
| `backend/` | FastAPI / API | `feature/backend` |
| `collector/` | 데이터 수집 | `feature/collector` |
| `rag/` | RAG / 검색 | `feature/rag` |
| `paper_generator/` | Transformer / 논문 생성 | `feature/paper-generator` |
| `database/` | PostgreSQL/pgvector + Neo4j (그래프 DB 포함) | `feature/database` |
| `tests/` | 통합 테스트 | - |
| `docs/` | 발표자료 / 설계 문서 | - |

> `neo4j/`는 별도 폴더로 안 쪼개고 `database/`에 합쳐서 관리 (Postgres·Neo4j 접속/스키마를
> 한 곳에서 관리하기 위함 — DB 담당자 논의로 결정).

## 작업 규칙

1. main에 직접 push하지 않기
2. 본인 담당 브랜치(`feature/xxx`)에서 작업
3. 작업 후 Commit → Push → Pull Request
4. 다른 사람 코드가 main에 합쳐지면 `git pull`로 최신화
5. `.env` / API Key / 비밀번호는 절대 커밋하지 않기 (`.env.example`에는 변수 이름만)
6. `docker-compose.yml`, `.env.example`, `README.md`, `.gitignore` 같은 공통 파일 수정 전엔 팀원에게 먼저 알리기

## 시작하기

```bash
git clone https://github.com/jaewon1214/art_project.git
cd art-paper-project
git checkout main && git pull origin main
git checkout -b feature/본인담당      # 처음이면 -b로 생성
```

각 폴더의 구체적인 실행 방법(환경변수, DB 기동, 파이프라인 실행 등)은 담당자가 각자
`<폴더>/README.md`(또는 이 파일 하단에 섹션 추가)로 채워나갈 예정.
