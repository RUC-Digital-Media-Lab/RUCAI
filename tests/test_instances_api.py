from fastapi.testclient import TestClient

import app.main as main
from app.auth import hash_password


def test_list_instances_success(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(
        main,
        "list_bot_instances_for_owner",
        lambda _conn, owner: [
            {
                "id": 1,
                "owner_username": owner,
                "source_course_id": 2,
                "name": "Hold A",
                "instance_code": "ABC234XY",
                "is_active": True,
                "created_at": "2026-02-20T21:00:00Z",
                "published_at": "2026-02-20T21:00:00Z",
                "chunk_count": 9,
            }
        ],
    )

    resp = client.get("/instances", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["instances"]) == 1
    assert data["instances"][0]["instance_code"] == "ABC234XY"


def test_publish_instance_success(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "_active_course_or_404", lambda _username: {"id": 2})
    monkeypatch.setattr(main, "get_course_prompt", lambda _conn, _cid: "Prompt")
    monkeypatch.setattr(
        main,
        "create_bot_instance",
        lambda **_kwargs: {
            "id": 7,
            "owner_username": "frede",
            "source_course_id": 2,
            "name": "Hold A",
            "instance_code": "ABC234XY",
            "is_active": True,
            "created_at": "2026-02-20T21:00:00Z",
            "published_at": "2026-02-20T21:00:00Z",
        },
    )
    monkeypatch.setattr(main, "copy_course_chunks_to_instance", lambda _conn, _cid, _iid: 14)

    resp = client.post(
        "/instances",
        headers=auth_headers,
        json={"name": "Hold A", "instance_code": "ABC234XY", "instance_password": "secretpw"},
    )
    assert resp.status_code == 200
    data = resp.json()["instance"]
    assert data["id"] == 7
    assert data["chunk_count"] == 14


def test_student_login_and_chat_success(client: TestClient, monkeypatch):
    hashed = hash_password("pw1234")
    monkeypatch.setattr(
        main,
        "get_bot_instance_by_code",
        lambda _conn, _code: {
            "id": 88,
            "name": "Hold A",
            "instance_code": "ABC234XY",
            "password_hash": hashed,
            "is_active": True,
        },
    )
    monkeypatch.setattr(
        main,
        "get_bot_instance_by_id",
        lambda _conn, iid: {
            "id": iid,
            "name": "Hold A",
            "instance_code": "ABC234XY",
            "effective_system_prompt_snapshot": "You are RUCAI",
            "is_active": True,
            "chunk_count": 2,
        },
    )
    monkeypatch.setattr(
        main,
        "search_instance_chunks",
        lambda _q, _settings, _k, _iid: [
            {"filename": "doc.pdf", "page_start": 1, "chunk_index": 0, "content": "Test content"}
        ],
    )
    monkeypatch.setattr(main, "generate_answer", lambda _prompt, _settings: "Svar [1]")

    login = client.post("/student/login", json={"instance_code": "ABC234XY", "password": "pw1234"})
    assert login.status_code == 200
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    meta = client.get("/student/instance", headers=headers)
    assert meta.status_code == 200
    assert meta.json()["instance"]["name"] == "Hold A"

    chat = client.post("/student/chat", headers=headers, json={"message": "hej", "k": 3})
    assert chat.status_code == 200
    body = chat.json()
    assert body["answer"] == "Svar [1]"
    assert body["source_count"] == 1
