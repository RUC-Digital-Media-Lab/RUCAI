from fastapi.testclient import TestClient

import app.main as main


def _active_course(_conn):
    return {
        "id": 3,
        "title": "Didaktik",
        "description": "desc",
        "is_active": True,
        "created_at": "2026-02-20T00:00:00+00:00",
    }


def test_search_is_course_scoped(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "get_active_course", _active_course)

    def fake_search(query, settings, top_k, course_id):
        assert course_id == 3
        return [{"filename": "a.pdf", "path": "/tmp/a.pdf", "page_start": 1, "page_end": 1, "chunk_index": 0, "content": "x", "distance": 0.1}]

    monkeypatch.setattr(main, "search_chunks", fake_search)

    resp = client.get("/search", params={"q": "begreb", "k": 2}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["course_id"] == 3
    assert len(data["results"]) == 1


def test_chat_returns_citations(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "get_active_course", _active_course)
    monkeypatch.setattr(main, "get_course_prompt", lambda conn, course_id: None)
    monkeypatch.setattr(
        main,
        "chat_response",
        lambda query, settings, top_k, course_id, editable_instructions=None: {
            "query": query,
            "k": top_k,
            "answer": "Svar [1]",
            "contexts": [],
            "citations": [{"ref": 1, "filename": "a.pdf", "page_start": 2, "chunk_index": 4}],
            "prompt": "p",
        },
    )

    resp = client.post("/chat", json={"message": "Forklar", "k": 4}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["course_id"] == 3
    assert data["citations"][0]["filename"] == "a.pdf"


def test_ingest_job_status(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_ingest_job",
        lambda conn, job_id: {
            "id": job_id,
            "course_id": 3,
            "document_id": 99,
            "path": "/tmp/p.pdf",
            "status": "running",
            "progress": 55,
            "error": None,
            "created_at": "2026-02-20T00:00:00+00:00",
            "updated_at": "2026-02-20T00:01:00+00:00",
        },
    )

    resp = client.get("/ingest/jobs/123", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["job"]["progress"] == 55
