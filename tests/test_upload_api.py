from fastapi.testclient import TestClient

import app.main as main


def test_upload_pdf_creates_job(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_active_course",
        lambda conn: {
            "id": 7,
            "title": "Kursus",
            "description": None,
            "is_active": True,
            "created_at": "2026-02-20T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(main, "create_ingest_job", lambda conn, course_id, path, scan_mode="digital": 42)
    monkeypatch.setattr(main, "_start_ingest_thread", lambda settings, job_id, course_id, path, scan_mode: None)

    files = {"file": ("pensum.pdf", b"%PDF-1.4 test", "application/pdf")}
    resp = client.post("/upload/pdf", headers=auth_headers, files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == 42
    assert data["course_id"] == 7


def test_upload_rejects_non_pdf(client: TestClient, auth_headers):
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    resp = client.post("/upload/pdf", headers=auth_headers, files=files)
    assert resp.status_code == 400


def test_upload_docx_creates_job(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_active_course",
        lambda conn: {
            "id": 7,
            "title": "Kursus",
            "description": None,
            "is_active": True,
            "created_at": "2026-02-20T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(main, "create_ingest_job", lambda conn, course_id, path, scan_mode="digital": 77)
    monkeypatch.setattr(main, "_start_ingest_thread", lambda settings, job_id, course_id, path, scan_mode: None)

    files = {
        "file": (
            "lecture.docx",
            b"PK\x03\x04fake-docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = client.post("/upload/document", headers=auth_headers, files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == 77
    assert data["course_id"] == 7


def test_upload_respects_scan_mode(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_active_course",
        lambda conn: {
            "id": 7,
            "title": "Kursus",
            "description": None,
            "is_active": True,
            "created_at": "2026-02-20T00:00:00+00:00",
        },
    )
    seen = {}

    def fake_create_ingest_job(conn, course_id, path, scan_mode="digital"):
        seen["scan_mode"] = scan_mode
        return 88

    monkeypatch.setattr(main, "create_ingest_job", fake_create_ingest_job)
    monkeypatch.setattr(main, "_start_ingest_thread", lambda settings, job_id, course_id, path, scan_mode: None)

    files = {"file": ("scan.pdf", b"%PDF-1.4 test", "application/pdf")}
    resp = client.post(
        "/upload/document",
        headers=auth_headers,
        files=files,
        data={"scan_mode": "hand_scanned"},
    )
    assert resp.status_code == 200
    assert seen["scan_mode"] == "hand_scanned"


def test_upload_multiple_documents(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_active_course",
        lambda conn: {
            "id": 7,
            "title": "Kursus",
            "description": None,
            "is_active": True,
            "created_at": "2026-02-20T00:00:00+00:00",
        },
    )
    job_ids = iter([101, 102])
    monkeypatch.setattr(main, "create_ingest_job", lambda conn, course_id, path, scan_mode="digital": next(job_ids))
    monkeypatch.setattr(main, "_start_ingest_thread", lambda settings, job_id, course_id, path, scan_mode: None)

    files = [
        ("files", ("lecture1.pdf", b"%PDF-1.4 test", "application/pdf")),
        ("files", ("lecture2.docx", b"PK\x03\x04fake-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
    ]
    resp = client.post("/upload/document", headers=auth_headers, files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["course_id"] == 7
    assert len(data["items"]) == 2
    assert data["items"][0]["job_id"] == 101
    assert data["items"][1]["job_id"] == 102
