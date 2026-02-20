from fastapi.testclient import TestClient

import app.main as main


def test_create_course_requires_auth(client: TestClient):
    resp = client.post("/course", json={"title": "AI Course", "description": "desc"})
    assert resp.status_code == 401


def test_create_course_success(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(
        main,
        "create_or_activate_course",
        lambda conn, title, description: {
            "id": 1,
            "title": title,
            "description": description,
            "is_active": True,
            "created_at": "2026-02-20T00:00:00+00:00",
        },
    )

    resp = client.post(
        "/course",
        json={"title": "RU Kursus", "description": "Lærerpilot"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["course"]["title"] == "RU Kursus"
