from typing import Iterable, List


def chunk_text(text: str, max_words: int, overlap: int) -> List[str]:
    words = text.split()
    if not words:
        return []

    if overlap >= max_words:
        raise ValueError("overlap must be smaller than max_words")

    chunks: List[str] = []
    step = max_words - overlap
    for start in range(0, len(words), step):
        end = start + max_words
        chunk_words = words[start:end]
        if not chunk_words:
            break
        chunks.append(" ".join(chunk_words))
        if end >= len(words):
            break
    return chunks


def normalize_text(text: str) -> str:
    # PostgreSQL text fields cannot contain NUL bytes.
    # Strip them early so all ingest paths are safe.
    sanitized = text.replace("\x00", " ")
    return " ".join(sanitized.split())


def iter_nonempty(chunks: Iterable[str]) -> Iterable[str]:
    for chunk in chunks:
        cleaned = chunk.strip()
        if cleaned:
            yield cleaned
