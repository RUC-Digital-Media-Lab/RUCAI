from fastapi.testclient import TestClient


def test_chat_requires_auth(client: TestClient):
    resp = client.post("/chat", json={"message": "hej", "k": 2})
    assert resp.status_code == 401
