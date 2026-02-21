import os
from typing import Dict

import httpx

from .config import Settings


def generate_answer(prompt: str, settings: Settings) -> str:
    url = f"{settings.ollama_base_url}/api/generate"
    keep_alive = os.getenv("CHAT_KEEP_ALIVE", "60s").strip() or "60s"
    payload: Dict[str, object] = {
        "model": settings.chat_model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive,
    }
    with httpx.Client(timeout=120) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    response = data.get("response")
    if not isinstance(response, str):
        raise RuntimeError("Ollama response missing response.")
    return response.strip()
