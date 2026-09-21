from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_root() -> None:
    response = client.get("/")

    assert response.status_code == 200

    data = response.json()

    assert "service" in data
    assert "version" in data
    assert data["docs"] == "/docs"


def test_health() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["service"] == "ai-music-paper-backend"


def test_search() -> None:
    response = client.post(
        "/api/v1/search",
        json={
            "topic": "생성형 AI 음악의 음성복제와 저작권",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert "contexts" in data
    assert "sources" in data

    assert len(data["contexts"]) > 0
    assert len(data["sources"]) > 0

    first_context = data["contexts"][0]

    assert first_context["chunk_id"] == "MOCK-CHUNK-001"
    assert first_context["document_id"] == "SRC001"
    assert first_context["content"]
    assert first_context["score"] == 0.95

    assert data["sources"][0]["source_id"] == "SRC001"


def test_generate() -> None:
    response = client.post(
        "/api/v1/generate",
        json={
            "topic": "생성형 AI 음악의 음성복제와 저작권",
            "length": 4500,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert "paper_id" in data
    assert "title" in data
    assert "abstract" in data
    assert "sections" in data
    assert "conclusion" in data
    assert "references" in data
    assert "paper_citations" in data

    assert len(data["sections"]) > 0
    assert len(data["references"]) > 0
    assert len(data["paper_citations"]) > 0

    citation = data["paper_citations"][0]

    assert "section" in citation
    assert "chunk_id" in citation
    assert "document_id" in citation
    assert "claim_text" in citation
    assert "relevance_score" in citation

    assert citation["chunk_id"].startswith(
        "MOCK-CHUNK-"
    )

    assert citation["document_id"] in {
        "SRC001",
        "SRC002",
    }

    assert citation["claim_text"]

    assert citation["relevance_score"] is not None


def test_generate_default_length() -> None:
    response = client.post(
        "/api/v1/generate",
        json={
            "topic": "AI 작곡과 창작자성",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert "paper_id" in data
    assert "sections" in data
    assert "paper_citations" in data

    assert len(data["paper_citations"]) > 0


def test_generate_topic_too_short() -> None:
    response = client.post(
        "/api/v1/generate",
        json={
            "topic": "AI",
            "length": 4500,
        },
    )

    assert response.status_code == 422


def test_generate_length_too_small() -> None:
    response = client.post(
        "/api/v1/generate",
        json={
            "topic": "AI 음악 저작권",
            "length": 500,
        },
    )

    assert response.status_code == 422


def test_generate_length_too_large() -> None:
    response = client.post(
        "/api/v1/generate",
        json={
            "topic": "AI 음악 저작권",
            "length": 50000,
        },
    )

    assert response.status_code == 422


def test_generate_with_title_preserves_exact_title() -> None:
    requested_title = (
        "소송에서 라이선스로: Suno·Udio와 메이저 레이블들의 "
        "합의가 생성형 음악 모델에 갖는 의미"
    )

    response = client.post(
        "/api/v1/generate",
        json={
            "title": requested_title,
            "topic": (
                "Suno·Udio와 메이저 레이블 간 합의가 "
                "생성형 음악 모델의 라이선스 구조에 미친 영향"
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["title"] == requested_title


def test_generate_title_too_short() -> None:
    response = client.post(
        "/api/v1/generate",
        json={
            "title": "AI",
            "topic": "생성형 AI 음악 저작권",
        },
    )

    assert response.status_code == 422
