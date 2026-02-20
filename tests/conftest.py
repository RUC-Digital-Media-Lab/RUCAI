from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings


class DummyConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        return None


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    settings = Settings(
        data_root=tmp_path / "data",
        upload_root=tmp_path / "uploads",
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_user="test",
        db_password="test",
        ollama_base_url="http://localhost:11434",
        embed_model="bge-m3",
        chat_model="gemma3",
        auth_username="frede",
        auth_password="secret",
        auth_users_file=tmp_path / "auth_users.json",
        auth_ttl_seconds=3600,
    )

    monkeypatch.setattr(main, "load_settings", lambda: settings)
    monkeypatch.setattr(main, "ensure_data_dirs", lambda _settings: None)
    monkeypatch.setattr(main, "ensure_schema", lambda _settings: None)
    monkeypatch.setattr(main, "get_connection", lambda _settings: DummyConn())

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient):
    resp = client.post("/auth/login", json={"username": "frede", "password": "secret"})
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
