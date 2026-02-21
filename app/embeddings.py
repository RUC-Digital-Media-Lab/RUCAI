import os
from typing import List

import httpx

from .config import Settings


def embed_text(text: str, settings: Settings) -> List[float]:
    keep_alive = os.getenv("EMBED_KEEP_ALIVE", "45s").strip() or "45s"
    legacy_url = f"{settings.ollama_base_url}/api/embeddings"
    legacy_payload = {
        "model": settings.embed_model,
        "prompt": text,
        "keep_alive": keep_alive,
    }
    embed_url = f"{settings.ollama_base_url}/api/embed"
    embed_payload = {
        "model": settings.embed_model,
        "input": text,
        "keep_alive": keep_alive,
    }

    with httpx.Client(timeout=60) as client:
        try:
            resp = client.post(legacy_url, json=legacy_payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            # Newer Ollama uses /api/embed instead of /api/embeddings.
            if exc.response.status_code != 404:
                raise
            resp = client.post(embed_url, json=embed_payload)
            resp.raise_for_status()
            data = resp.json()

    embedding = data.get("embedding")
    if isinstance(embedding, list):
        return embedding

    embeddings = data.get("embeddings")
    if isinstance(embeddings, list) and embeddings:
        first = embeddings[0]
        if isinstance(first, list):
            return first

    raise RuntimeError("Ollama embedding response missing embedding vector.")
