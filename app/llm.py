import os
from typing import Dict

import httpx

from .config import Settings


def _chat_num_ctx() -> int:
    raw = os.getenv("CHAT_NUM_CTX", "8192").strip()
    try:
        value = int(raw)
    except ValueError:
        return 8192
    return value if value > 0 else 8192


def generate_answer(prompt: str, settings: Settings) -> str:
    url = f"{settings.ollama_base_url}/api/generate"
    keep_alive = os.getenv("CHAT_KEEP_ALIVE", "60s").strip() or "60s"
    num_ctx = _chat_num_ctx()
    payload: Dict[str, object] = {
        "model": settings.chat_model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "num_ctx": num_ctx,
        },
    }
    with httpx.Client(timeout=120) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    response = data.get("response")
    if not isinstance(response, str):
        raise RuntimeError("Ollama response missing response.")
    return response.strip()
