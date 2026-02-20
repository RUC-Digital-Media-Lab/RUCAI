from fastapi.testclient import TestClient


def test_search_requires_auth(client: TestClient):
    resp = client.get("/search", params={"q": "test", "k": 3})
    assert resp.status_code == 401
