from fastapi.testclient import TestClient


def test_login_success(client: TestClient):
    resp = client.post("/auth/login", json={"username": "frede", "password": "secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert isinstance(data["token"], str)
    assert len(data["token"]) > 10


def test_login_failure(client: TestClient):
    resp = client.post("/auth/login", json={"username": "frede", "password": "wrong"})
    assert resp.status_code == 401
