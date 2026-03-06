from __future__ import annotations

import re

CHUNK_ROLE_CONTENT = "content"
CHUNK_ROLE_REFERENCE = "reference"


def looks_like_reference_text(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    low = text.lower()

    keyword_hits = sum(
        1
        for k in [
            "references",
            "bibliography",
            "acknowledgements",
            "declaration of conflicting interests",
            "litteratur",
            "referencer",
            "kildeliste",
            "works cited",
        ]
        if k in low
    )
    citation_hits = len(re.findall(r"\([12][0-9]{3}\)", text))
    doi_hits = len(re.findall(r"\bdoi[:\s]", low))
    journal_hits = len(
        re.findall(
            r"\b(journal|press|review|studies|communication|organization|doi|vol\.|pp\.)\b",
            low,
        )
    )
    author_year_list_hits = len(
        re.findall(r"[A-ZÆØÅ][A-Za-zÆØÅæøå'’\-\s]+,\s*[A-ZÆØÅ]\.\s*\([12][0-9]{3}\)", text)
    )
    many_semicolons = text.count(";") >= 3
    return (
        keyword_hits >= 1
        or citation_hits >= 2
        or doi_hits >= 1
        or journal_hits >= 3
        or author_year_list_hits >= 2
        or many_semicolons
    )


def classify_chunk_role(content: str) -> str:
    return CHUNK_ROLE_REFERENCE if looks_like_reference_text(content) else CHUNK_ROLE_CONTENT
