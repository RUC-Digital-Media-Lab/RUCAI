import httpx

from app.config import Settings
from app.embeddings import embed_text


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("POST", "http://localhost")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=self.request, response=self)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses):
        self._responses = list(responses)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, _url, json=None):
        assert isinstance(json, dict)
        return self._responses.pop(0)


def _settings() -> Settings:
    return Settings(
        data_root="/tmp",  # type: ignore[arg-type]
        upload_root="/tmp",  # type: ignore[arg-type]
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_user="test",
        db_password="test",
        ollama_base_url="http://localhost:11434",
        embed_model="bge-m3",
        chat_model="gemma3:12b",
        auth_username="frede",
        auth_password="secret",
        auth_users_file="/tmp/auth_users.json",  # type: ignore[arg-type]
        auth_ttl_seconds=3600,
    )


def test_embed_text_falls_back_to_api_embed(monkeypatch):
    responses = [
        _Resp(404, {"error": "not found"}),
        _Resp(200, {"embeddings": [[0.1, 0.2, 0.3]]}),
    ]
    monkeypatch.setattr(httpx, "Client", lambda timeout=60: _Client(responses))

    out = embed_text("hej", _settings())
    assert out == [0.1, 0.2, 0.3]


def test_embed_text_accepts_legacy_embedding_field(monkeypatch):
    responses = [_Resp(200, {"embedding": [1.0, 2.0]})]
    monkeypatch.setattr(httpx, "Client", lambda timeout=60: _Client(responses))

    out = embed_text("hej", _settings())
    assert out == [1.0, 2.0]
