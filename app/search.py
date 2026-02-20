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
) -> List[Dict[str, Any]]:
    if not query.strip():
        return []

    embedding = Vector(embed_text(query, settings))

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
                (embedding, course_id, embedding, top_k),
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

    return results


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
