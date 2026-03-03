from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import psycopg
from pgvector.psycopg import register_vector

from .config import Settings


VALID_JOB_STATUSES = {"queued", "running", "done", "failed"}


def get_connection(settings: Settings) -> psycopg.Connection:
    conn = psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        autocommit=False,
    )
    register_vector(conn)
    return conn


def ensure_schema(settings: Settings) -> None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS courses (
                    id BIGSERIAL PRIMARY KEY,
                    owner_username TEXT,
                    title TEXT NOT NULL,
                    description TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'courses'
                      AND column_name = 'owner_username'
                );
                """
            )
            has_owner_username = cur.fetchone()[0]
            if not has_owner_username:
                cur.execute("ALTER TABLE courses ADD COLUMN owner_username TEXT;")
            cur.execute(
                """
                UPDATE courses
                SET owner_username = %s
                WHERE owner_username IS NULL OR owner_username = '';
                """,
                (settings.auth_username,),
            )
            cur.execute("ALTER TABLE courses ALTER COLUMN owner_username SET NOT NULL;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS course_prompts (
                    id BIGSERIAL PRIMARY KEY,
                    course_id BIGINT NOT NULL UNIQUE REFERENCES courses(id) ON DELETE CASCADE,
                    editable_instructions TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute("DROP INDEX IF EXISTS idx_courses_single_active;")
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_active_by_owner
                ON courses (owner_username)
                WHERE is_active = TRUE;
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id BIGSERIAL PRIMARY KEY,
                    course_id BIGINT REFERENCES courses(id) ON DELETE CASCADE,
                    path TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    language TEXT,
                    source TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'documents'
                      AND column_name = 'course_id'
                );
                """
            )
            has_course_id = cur.fetchone()[0]
            if not has_course_id:
                cur.execute("ALTER TABLE documents ADD COLUMN course_id BIGINT;")
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'documents'
                      AND column_name = 'language'
                );
                """
            )
            has_language = cur.fetchone()[0]
            if not has_language:
                cur.execute("ALTER TABLE documents ADD COLUMN language TEXT;")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    section_title TEXT,
                    content TEXT NOT NULL,
                    embedding vector,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_document_id
                ON chunks(document_id);
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_jobs (
                    id BIGSERIAL PRIMARY KEY,
                    course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
                    path TEXT NOT NULL,
                    scan_mode TEXT NOT NULL DEFAULT 'digital',
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id BIGSERIAL PRIMARY KEY,
                    course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_course_id
                ON chat_messages(course_id);
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_instances (
                    id BIGSERIAL PRIMARY KEY,
                    owner_username TEXT NOT NULL,
                    source_course_id BIGINT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    instance_code TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    editable_instructions_snapshot TEXT NOT NULL,
                    locked_safety_block_snapshot TEXT NOT NULL,
                    effective_system_prompt_snapshot TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bot_instances_owner
                ON bot_instances(owner_username);
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS student_chat_messages (
                    id BIGSERIAL PRIMARY KEY,
                    instance_id BIGINT NOT NULL REFERENCES bot_instances(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_student_chat_messages_instance_id
                ON student_chat_messages(instance_id);
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_instance_chunks (
                    id BIGSERIAL PRIMARY KEY,
                    instance_id BIGINT NOT NULL REFERENCES bot_instances(id) ON DELETE CASCADE,
                    source_document_id BIGINT,
                    filename TEXT NOT NULL,
                    page_start INTEGER,
                    chunk_index INTEGER,
                    content TEXT NOT NULL,
                    embedding vector,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bot_instance_chunks_instance_id
                ON bot_instance_chunks(instance_id);
                """
            )
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'ingest_jobs'
                      AND column_name = 'scan_mode'
                );
                """
            )
            has_scan_mode = cur.fetchone()[0]
            if not has_scan_mode:
                cur.execute(
                    """
                    ALTER TABLE ingest_jobs
                    ADD COLUMN scan_mode TEXT NOT NULL DEFAULT 'digital';
                    """
                )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingest_jobs_course_id
                ON ingest_jobs(course_id);
                """
            )

            # Legacy migration path: existing deployments may have documents without course_id.
            cur.execute(
                """
                SELECT id FROM courses
                WHERE is_active = TRUE AND owner_username = %s
                LIMIT 1;
                """,
                (settings.auth_username,),
            )
            active_course = cur.fetchone()
            if active_course:
                active_course_id = active_course[0]
            else:
                cur.execute(
                    """
                    INSERT INTO courses (owner_username, title, description, is_active)
                    VALUES (%s, 'Legacy Course', 'Auto-created migration course', TRUE)
                    RETURNING id;
                    """
                    ,
                    (settings.auth_username,),
                )
                active_course_id = cur.fetchone()[0]

            cur.execute(
                "UPDATE documents SET course_id = %s WHERE course_id IS NULL;",
                (active_course_id,),
            )

            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'documents_course_id_fkey'
                );
                """
            )
            has_doc_course_fk = cur.fetchone()[0]
            if not has_doc_course_fk:
                cur.execute(
                    """
                    ALTER TABLE documents
                    ADD CONSTRAINT documents_course_id_fkey
                    FOREIGN KEY (course_id)
                    REFERENCES courses(id)
                    ON DELETE CASCADE;
                    """
                )

            cur.execute("ALTER TABLE documents ALTER COLUMN course_id SET NOT NULL;")
        conn.commit()


def _course_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "owner_username": row[1],
        "title": row[2],
        "description": row[3],
        "is_active": row[4],
        "created_at": row[5].isoformat() if isinstance(row[5], datetime) else row[5],
    }


def create_or_activate_course(
    conn: psycopg.Connection,
    owner_username: str,
    title: str,
    description: Optional[str],
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE courses SET is_active = FALSE WHERE is_active = TRUE AND owner_username = %s;",
            (owner_username,),
        )
        cur.execute(
            """
            INSERT INTO courses (owner_username, title, description, is_active)
            VALUES (%s, %s, %s, TRUE)
            RETURNING id, owner_username, title, description, is_active, created_at;
            """,
            (owner_username, title, description),
        )
        row = cur.fetchone()
    return _course_row_to_dict(row)


def get_active_course(conn: psycopg.Connection, owner_username: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, owner_username, title, description, is_active, created_at
            FROM courses
            WHERE is_active = TRUE
              AND owner_username = %s
            LIMIT 1;
            """,
            (owner_username,),
        )
        row = cur.fetchone()
    return _course_row_to_dict(row) if row else None


def list_courses(conn: psycopg.Connection, owner_username: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, owner_username, title, description, is_active, created_at
            FROM courses
            WHERE owner_username = %s
            ORDER BY is_active DESC, created_at DESC;
            """,
            (owner_username,),
        )
        rows = cur.fetchall()
    return [_course_row_to_dict(row) for row in rows]


def set_active_course_by_id(
    conn: psycopg.Connection,
    owner_username: str,
    course_id: int,
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM courses WHERE id = %s AND owner_username = %s;",
            (course_id, owner_username),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            "UPDATE courses SET is_active = FALSE WHERE is_active = TRUE AND owner_username = %s;",
            (owner_username,),
        )
        cur.execute(
            "UPDATE courses SET is_active = TRUE WHERE id = %s AND owner_username = %s;",
            (course_id, owner_username),
        )
        cur.execute(
            """
            SELECT id, owner_username, title, description, is_active, created_at
            FROM courses
            WHERE id = %s
              AND owner_username = %s;
            """,
            (course_id, owner_username),
        )
        course_row = cur.fetchone()
    return _course_row_to_dict(course_row) if course_row else None


def course_belongs_to_owner(conn: psycopg.Connection, course_id: int, owner_username: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS(
                SELECT 1
                FROM courses
                WHERE id = %s
                  AND owner_username = %s
            );
            """,
            (course_id, owner_username),
        )
        return bool(cur.fetchone()[0])


def get_or_create_document(
    conn: psycopg.Connection,
    course_id: int,
    path: str,
    filename: str,
    source: Optional[str],
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (course_id, path, filename, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (path) DO UPDATE
            SET course_id = EXCLUDED.course_id,
                filename = EXCLUDED.filename,
                source = EXCLUDED.source
            RETURNING id;
            """,
            (course_id, path, filename, source),
        )
        doc_id = cur.fetchone()[0]
    return doc_id


def document_belongs_to_course(
    conn: psycopg.Connection,
    document_id: int,
    course_id: int,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM documents
                WHERE id = %s AND course_id = %s
            );
            """,
            (document_id, course_id),
        )
        return bool(cur.fetchone()[0])


def set_document_language(
    conn: psycopg.Connection,
    document_id: int,
    language: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET language = %s
            WHERE id = %s;
            """,
            (language, document_id),
        )


def list_documents_for_course(
    conn: psycopg.Connection,
    course_id: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.filename, d.path, d.language, d.created_at,
                   COALESCE(cn.chunk_count, 0) AS chunk_count,
                   ij.scan_mode
            FROM documents d
            LEFT JOIN (
                SELECT document_id, COUNT(*) AS chunk_count
                FROM chunks
                GROUP BY document_id
            ) cn ON cn.document_id = d.id
            LEFT JOIN LATERAL (
                SELECT scan_mode
                FROM ingest_jobs
                WHERE document_id = d.id
                ORDER BY id DESC
                LIMIT 1
            ) ij ON TRUE
            WHERE d.course_id = %s
            ORDER BY d.created_at DESC;
            """,
            (course_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "filename": row[1],
            "path": row[2],
            "language": row[3],
            "created_at": row[4].isoformat() if isinstance(row[4], datetime) else row[4],
            "chunk_count": row[5],
            "scan_mode": row[6] or "digital",
        }
        for row in rows
    ]


def get_document(
    conn: psycopg.Connection,
    document_id: int,
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, course_id, filename, path, language, source
            FROM documents
            WHERE id = %s;
            """,
            (document_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "course_id": row[1],
        "filename": row[2],
        "path": row[3],
        "language": row[4],
        "source": row[5],
    }


def delete_document(
    conn: psycopg.Connection,
    document_id: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s;", (document_id,))


def get_course_prompt(
    conn: psycopg.Connection,
    course_id: int,
) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT editable_instructions
            FROM course_prompts
            WHERE course_id = %s
            LIMIT 1;
            """,
            (course_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return row[0]


def upsert_course_prompt(
    conn: psycopg.Connection,
    course_id: int,
    editable_instructions: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO course_prompts (course_id, editable_instructions)
            VALUES (%s, %s)
            ON CONFLICT (course_id) DO UPDATE
            SET editable_instructions = EXCLUDED.editable_instructions,
                updated_at = NOW();
            """,
            (course_id, editable_instructions),
        )


def clear_chunks(conn: psycopg.Connection, document_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE document_id = %s;", (document_id,))


def insert_chunk(
    conn: psycopg.Connection,
    document_id: int,
    chunk_index: int,
    page_start: int,
    page_end: int,
    section_title: Optional[str],
    content: str,
    embedding: Optional[list[float]],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chunks (
                document_id,
                chunk_index,
                page_start,
                page_end,
                section_title,
                content,
                embedding
            ) VALUES (%s, %s, %s, %s, %s, %s, %s);
            """,
            (
                document_id,
                chunk_index,
                page_start,
                page_end,
                section_title,
                content,
                embedding,
            ),
        )


def create_ingest_job(
    conn: psycopg.Connection,
    course_id: int,
    path: str,
    scan_mode: str = "digital",
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingest_jobs (course_id, path, scan_mode, status, progress)
            VALUES (%s, %s, %s, 'queued', 0)
            RETURNING id;
            """,
            (course_id, path, scan_mode),
        )
        job_id = cur.fetchone()[0]
    return job_id


def update_ingest_job(
    conn: psycopg.Connection,
    job_id: int,
    *,
    status: str,
    progress: int,
    error: Optional[str] = None,
    document_id: Optional[int] = None,
) -> None:
    if status not in VALID_JOB_STATUSES:
        raise ValueError(f"Invalid job status: {status}")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingest_jobs
            SET status = %s,
                progress = %s,
                error = %s,
                document_id = COALESCE(%s, document_id),
                updated_at = NOW()
            WHERE id = %s;
            """,
            (status, progress, error, document_id, job_id),
        )


def get_ingest_job(conn: psycopg.Connection, job_id: int) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT j.id, j.course_id, j.document_id, j.path, j.scan_mode, j.status, j.progress, j.error,
                   j.created_at, j.updated_at, d.language,
                   COALESCE(cnt.chunk_count, 0) AS chunk_count
            FROM ingest_jobs j
            LEFT JOIN documents d ON d.id = j.document_id
            LEFT JOIN (
                SELECT document_id, COUNT(*) AS chunk_count
                FROM chunks
                GROUP BY document_id
            ) cnt ON cnt.document_id = d.id
            WHERE j.id = %s;
            """,
            (job_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "course_id": row[1],
        "document_id": row[2],
        "path": row[3],
        "scan_mode": row[4],
        "status": row[5],
        "progress": row[6],
        "error": row[7],
        "created_at": row[8].isoformat() if isinstance(row[8], datetime) else row[8],
        "updated_at": row[9].isoformat() if isinstance(row[9], datetime) else row[9],
        "document_language": row[10],
        "chunk_count": row[11],
    }


def insert_chat_message(conn: psycopg.Connection, course_id: int, role: str, content: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_messages (course_id, role, content)
            VALUES (%s, %s, %s);
            """,
            (course_id, role, content),
        )


def list_chat_messages_for_course(
    conn: psycopg.Connection,
    course_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    capped_limit = max(1, min(limit, 500))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, role, content, created_at
            FROM chat_messages
            WHERE course_id = %s
            ORDER BY created_at ASC
            LIMIT %s;
            """,
            (course_id, capped_limit),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "created_at": row[3].isoformat() if isinstance(row[3], datetime) else row[3],
        }
        for row in rows
    ]


def delete_chat_messages_for_course(conn: psycopg.Connection, course_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM chat_messages
            WHERE course_id = %s
            RETURNING id;
            """,
            (course_id,),
        )
        rows = cur.fetchall()
    return len(rows)


def insert_student_chat_message(conn: psycopg.Connection, instance_id: int, role: str, content: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO student_chat_messages (instance_id, role, content)
            VALUES (%s, %s, %s);
            """,
            (instance_id, role, content),
        )


def list_student_chat_messages_for_instance(
    conn: psycopg.Connection,
    instance_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    capped_limit = max(1, min(limit, 500))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, role, content, created_at
            FROM student_chat_messages
            WHERE instance_id = %s
            ORDER BY created_at ASC
            LIMIT %s;
            """,
            (instance_id, capped_limit),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "created_at": row[3].isoformat() if isinstance(row[3], datetime) else row[3],
        }
        for row in rows
    ]


def create_bot_instance(
    conn: psycopg.Connection,
    owner_username: str,
    source_course_id: int,
    name: str,
    instance_code: str,
    password_hash: str,
    editable_instructions_snapshot: str,
    locked_safety_block_snapshot: str,
    effective_system_prompt_snapshot: str,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bot_instances (
                owner_username,
                source_course_id,
                name,
                instance_code,
                password_hash,
                is_active,
                editable_instructions_snapshot,
                locked_safety_block_snapshot,
                effective_system_prompt_snapshot
            )
            VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s, %s)
            RETURNING id, owner_username, source_course_id, name, instance_code, is_active, created_at, published_at;
            """,
            (
                owner_username,
                source_course_id,
                name,
                instance_code,
                password_hash,
                editable_instructions_snapshot,
                locked_safety_block_snapshot,
                effective_system_prompt_snapshot,
            ),
        )
        row = cur.fetchone()
    return {
        "id": row[0],
        "owner_username": row[1],
        "source_course_id": row[2],
        "name": row[3],
        "instance_code": row[4],
        "is_active": row[5],
        "created_at": row[6].isoformat() if isinstance(row[6], datetime) else row[6],
        "published_at": row[7].isoformat() if isinstance(row[7], datetime) else row[7],
    }


def copy_course_chunks_to_instance(
    conn: psycopg.Connection,
    source_course_id: int,
    instance_id: int,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bot_instance_chunks (
                instance_id,
                source_document_id,
                filename,
                page_start,
                chunk_index,
                content,
                embedding
            )
            SELECT
                %s,
                d.id,
                d.filename,
                c.page_start,
                c.chunk_index,
                c.content,
                c.embedding
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.course_id = %s
            RETURNING id;
            """,
            (instance_id, source_course_id),
        )
        rows = cur.fetchall()
    return len(rows)


def list_bot_instances_for_owner(conn: psycopg.Connection, owner_username: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                i.id,
                i.owner_username,
                i.source_course_id,
                i.name,
                i.instance_code,
                i.is_active,
                i.created_at,
                i.published_at,
                COALESCE(cnt.chunk_count, 0) AS chunk_count
            FROM bot_instances i
            LEFT JOIN (
                SELECT instance_id, COUNT(*) AS chunk_count
                FROM bot_instance_chunks
                GROUP BY instance_id
            ) cnt ON cnt.instance_id = i.id
            WHERE i.owner_username = %s
            ORDER BY i.published_at DESC;
            """,
            (owner_username,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "owner_username": row[1],
            "source_course_id": row[2],
            "name": row[3],
            "instance_code": row[4],
            "is_active": row[5],
            "created_at": row[6].isoformat() if isinstance(row[6], datetime) else row[6],
            "published_at": row[7].isoformat() if isinstance(row[7], datetime) else row[7],
            "chunk_count": row[8],
        }
        for row in rows
    ]


def get_bot_instance_for_owner(
    conn: psycopg.Connection,
    instance_id: int,
    owner_username: str,
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                i.id,
                i.owner_username,
                i.source_course_id,
                i.name,
                i.instance_code,
                i.password_hash,
                i.is_active,
                i.editable_instructions_snapshot,
                i.locked_safety_block_snapshot,
                i.effective_system_prompt_snapshot,
                i.created_at,
                i.published_at,
                COALESCE(cnt.chunk_count, 0) AS chunk_count
            FROM bot_instances i
            LEFT JOIN (
                SELECT instance_id, COUNT(*) AS chunk_count
                FROM bot_instance_chunks
                GROUP BY instance_id
            ) cnt ON cnt.instance_id = i.id
            WHERE i.id = %s
              AND i.owner_username = %s
            LIMIT 1;
            """,
            (instance_id, owner_username),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "owner_username": row[1],
        "source_course_id": row[2],
        "name": row[3],
        "instance_code": row[4],
        "password_hash": row[5],
        "is_active": row[6],
        "editable_instructions_snapshot": row[7],
        "locked_safety_block_snapshot": row[8],
        "effective_system_prompt_snapshot": row[9],
        "created_at": row[10].isoformat() if isinstance(row[10], datetime) else row[10],
        "published_at": row[11].isoformat() if isinstance(row[11], datetime) else row[11],
        "chunk_count": row[12],
    }


def set_bot_instance_status(
    conn: psycopg.Connection,
    instance_id: int,
    owner_username: str,
    is_active: bool,
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bot_instances
            SET is_active = %s
            WHERE id = %s
              AND owner_username = %s
            RETURNING id;
            """,
            (is_active, instance_id, owner_username),
        )
        row = cur.fetchone()
        if not row:
            return None
    return get_bot_instance_for_owner(conn, instance_id, owner_username)


def get_bot_instance_by_code(conn: psycopg.Connection, instance_code: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                i.id,
                i.owner_username,
                i.source_course_id,
                i.name,
                i.instance_code,
                i.password_hash,
                i.is_active,
                i.editable_instructions_snapshot,
                i.locked_safety_block_snapshot,
                i.effective_system_prompt_snapshot,
                i.created_at,
                i.published_at,
                COALESCE(cnt.chunk_count, 0) AS chunk_count
            FROM bot_instances i
            LEFT JOIN (
                SELECT instance_id, COUNT(*) AS chunk_count
                FROM bot_instance_chunks
                GROUP BY instance_id
            ) cnt ON cnt.instance_id = i.id
            WHERE i.instance_code = %s
            LIMIT 1;
            """,
            (instance_code,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "owner_username": row[1],
        "source_course_id": row[2],
        "name": row[3],
        "instance_code": row[4],
        "password_hash": row[5],
        "is_active": row[6],
        "editable_instructions_snapshot": row[7],
        "locked_safety_block_snapshot": row[8],
        "effective_system_prompt_snapshot": row[9],
        "created_at": row[10].isoformat() if isinstance(row[10], datetime) else row[10],
        "published_at": row[11].isoformat() if isinstance(row[11], datetime) else row[11],
        "chunk_count": row[12],
    }


def get_bot_instance_by_id(conn: psycopg.Connection, instance_id: int) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                i.id,
                i.owner_username,
                i.source_course_id,
                i.name,
                i.instance_code,
                i.password_hash,
                i.is_active,
                i.editable_instructions_snapshot,
                i.locked_safety_block_snapshot,
                i.effective_system_prompt_snapshot,
                i.created_at,
                i.published_at,
                COALESCE(cnt.chunk_count, 0) AS chunk_count
            FROM bot_instances i
            LEFT JOIN (
                SELECT instance_id, COUNT(*) AS chunk_count
                FROM bot_instance_chunks
                GROUP BY instance_id
            ) cnt ON cnt.instance_id = i.id
            WHERE i.id = %s
            LIMIT 1;
            """,
            (instance_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "owner_username": row[1],
        "source_course_id": row[2],
        "name": row[3],
        "instance_code": row[4],
        "password_hash": row[5],
        "is_active": row[6],
        "editable_instructions_snapshot": row[7],
        "locked_safety_block_snapshot": row[8],
        "effective_system_prompt_snapshot": row[9],
        "created_at": row[10].isoformat() if isinstance(row[10], datetime) else row[10],
        "published_at": row[11].isoformat() if isinstance(row[11], datetime) else row[11],
        "chunk_count": row[12],
    }


def list_bot_instance_documents(conn: psycopg.Connection, instance_id: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                filename,
                COUNT(*) AS chunk_count
            FROM bot_instance_chunks
            WHERE instance_id = %s
            GROUP BY filename
            ORDER BY filename ASC;
            """,
            (instance_id,),
        )
        rows = cur.fetchall()
    return [{"filename": row[0], "chunk_count": row[1]} for row in rows]
