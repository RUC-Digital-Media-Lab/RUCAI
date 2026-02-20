from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main


def test_get_course_prompt_default(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "_active_course_or_404", lambda: {"id": 5})
    monkeypatch.setattr(main, "get_course_prompt", lambda conn, course_id: None)

    resp = client.get("/course/prompt", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "editable_instructions" in data
    assert "locked_safety_block" in data


def test_update_course_prompt(client: TestClient, auth_headers, monkeypatch):
    saved = {}
    monkeypatch.setattr(main, "_active_course_or_404", lambda: {"id": 5})

    def fake_upsert(conn, course_id, editable_instructions):
        saved["course_id"] = course_id
        saved["editable"] = editable_instructions

    monkeypatch.setattr(main, "upsert_course_prompt", fake_upsert)

    resp = client.put(
        "/course/prompt",
        headers=auth_headers,
        json={"editable_instructions": "Brug case-baserede svar."},
    )
    assert resp.status_code == 200
    assert saved["course_id"] == 5
    assert "case-baserede" in saved["editable"]


def test_list_documents(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "_active_course_or_404", lambda: {"id": 7})
    monkeypatch.setattr(
        main,
        "list_documents_for_course",
        lambda conn, course_id: [
            {
                "id": 1,
                "filename": "a.pdf",
                "path": "/tmp/a.pdf",
                "language": "da",
                "created_at": "2026-02-20T00:00:00+00:00",
                "chunk_count": 11,
                "scan_mode": "digital",
            }
        ],
    )

    resp = client.get("/documents", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["documents"][0]["filename"] == "a.pdf"


def test_delete_document(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "_active_course_or_404", lambda: {"id": 7})
    monkeypatch.setattr(main, "document_belongs_to_course", lambda conn, document_id, course_id: True)
    called = {"deleted": False}

    def fake_delete(conn, document_id):
        called["deleted"] = True

    monkeypatch.setattr(main, "delete_document", fake_delete)

    resp = client.delete("/documents/1", headers=auth_headers)
    assert resp.status_code == 200
    assert called["deleted"] is True


def test_reingest_document(client: TestClient, auth_headers, monkeypatch, tmp_path: Path):
    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(main, "_active_course_or_404", lambda: {"id": 7})
    monkeypatch.setattr(main, "document_belongs_to_course", lambda conn, document_id, course_id: True)
    monkeypatch.setattr(
        main,
        "get_document",
        lambda conn, document_id: {
            "id": document_id,
            "course_id": 7,
            "filename": "doc.pdf",
            "path": str(file_path),
            "language": None,
            "source": str(tmp_path),
        },
    )
    monkeypatch.setattr(main, "create_ingest_job", lambda conn, course_id, path, scan_mode="digital": 55)
    monkeypatch.setattr(main, "_start_ingest_thread", lambda settings, job_id, course_id, path, scan_mode: None)

    resp = client.post(
        "/documents/99/reingest",
        headers=auth_headers,
        json={"scan_mode": "hand_scanned"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == 55
    assert data["scan_mode"] == "hand_scanned"
