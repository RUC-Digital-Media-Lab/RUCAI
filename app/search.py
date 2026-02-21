from typing import Any, Dict, List

from pgvector import Vector

from .config import Settings
from .db import get_connection
from .embeddings import embed_text


def search_chunks(
    query: str,
    settings: Settings,
    top_k: int,
    course_id: int,
    *,
    diversify_by_document: bool = False,
    max_per_document: int = 2,
    candidate_multiplier: int = 8,
) -> List[Dict[str, Any]]:
    if not query.strip():
        return []

    embedding = Vector(embed_text(query, settings))

    candidate_limit = max(top_k, top_k * max(1, candidate_multiplier))

    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.filename,
                    d.path,
                    c.page_start,
                    c.page_end,
                    c.chunk_index,
                    c.content,
                    (c.embedding <=> %s) AS distance
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.embedding IS NOT NULL
                  AND d.course_id = %s
                ORDER BY c.embedding <=> %s
                LIMIT %s;
                """,
                (embedding, course_id, embedding, candidate_limit),
            )
            rows = cur.fetchall()

    results = []
    for row in rows:
        results.append(
            {
                "filename": row[0],
                "path": row[1],
                "page_start": row[2],
                "page_end": row[3],
                "chunk_index": row[4],
                "content": row[5],
                "distance": float(row[6]) if row[6] is not None else None,
            }
        )

    if not diversify_by_document:
        return results[:top_k]

    # Keep relevance ordering but prevent one document from dominating.
    per_doc_used: Dict[str, int] = {}
    selected: List[Dict[str, Any]] = []
    for item in results:
        key = str(item["path"])
        used = per_doc_used.get(key, 0)
        if used >= max(1, max_per_document):
            continue
        selected.append(item)
        per_doc_used[key] = used + 1
        if len(selected) >= top_k:
            break

    if len(selected) < top_k:
        seen_ids = {id(x) for x in selected}
        for item in results:
            if id(item) in seen_ids:
                continue
            selected.append(item)
            if len(selected) >= top_k:
                break

    return selected


def search_instance_chunks(
    query: str,
    settings: Settings,
    top_k: int,
    instance_id: int,
) -> List[Dict[str, Any]]:
    if not query.strip():
        return []

    embedding = Vector(embed_text(query, settings))

    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    filename,
                    page_start,
                    chunk_index,
                    content,
                    (embedding <=> %s) AS distance
                FROM bot_instance_chunks
                WHERE embedding IS NOT NULL
                  AND instance_id = %s
                ORDER BY embedding <=> %s
                LIMIT %s;
                """,
                (embedding, instance_id, embedding, top_k),
            )
            rows = cur.fetchall()

    return [
        {
            "filename": row[0],
            "page_start": row[1],
            "chunk_index": row[2],
            "content": row[3],
            "distance": float(row[4]) if row[4] is not None else None,
        }
        for row in rows
    ]
