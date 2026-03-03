import os


def test_runtime_model_requires_auth(client):
    resp = client.get("/runtime/model")
    assert resp.status_code == 401


def test_runtime_model_get_and_set(client, auth_headers, monkeypatch):
    monkeypatch.setenv("CHAT_MODEL_OPTIONS", "gemma3:12b,qwen2.5:14b-instruct")

    get_resp = client.get("/runtime/model", headers=auth_headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["active_model"] == "gemma3:12b"
    assert "qwen2.5:14b-instruct" in body["options"]

    set_resp = client.put("/runtime/model", headers=auth_headers, json={"chat_model": "qwen2.5:14b-instruct"})
    assert set_resp.status_code == 200
    assert set_resp.json()["active_model"] == "qwen2.5:14b-instruct"
    assert os.environ.get("CHAT_MODEL") == "qwen2.5:14b-instruct"
