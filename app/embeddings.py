from typing import List

import httpx

from .config import Settings


def embed_text(text: str, settings: Settings) -> List[float]:
    url = f"{settings.ollama_base_url}/api/embeddings"
    payload = {
        "model": settings.embed_model,
        "prompt": text,
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    embedding = data.get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError("Ollama embedding response missing 'embedding'.")
    return embedding
