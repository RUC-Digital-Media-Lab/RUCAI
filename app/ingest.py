from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from docling.document_converter import DocumentConverter
from docx import Document
from pypdf import PdfReader

from .chunking import chunk_text, iter_nonempty, normalize_text
from .config import Settings
from .db import (
    clear_chunks,
    get_connection,
    get_or_create_document,
    insert_chunk,
    set_document_language,
    update_ingest_job,
)
from .embeddings import embed_text


logger = logging.getLogger("rucai.ingest")


def extract_page_text_pypdf(reader: PdfReader, page_number: int) -> str:
    page = reader.pages[page_number - 1]
    return page.extract_text() or ""


def extract_page_text_docling(
    converter: DocumentConverter, pdf_path: Path, page_number: int
) -> str:
    result = converter.convert(str(pdf_path), page_range=(page_number, page_number))
    if result.document is None:
        return ""
    return result.document.export_to_text()


def is_ocr_noise(text: str, min_chars: int, min_alpha_ratio: float) -> bool:
    nonspace = [c for c in text if not c.isspace()]
    if len(nonspace) < min_chars:
        return False
    alpha = sum(1 for c in nonspace if c.isalpha())
    ratio = alpha / len(nonspace) if nonspace else 0.0
    return ratio < min_alpha_ratio


def extract_text_mineru(pdf_path: Path) -> str:
    mineru_cmd = shutil.which("mineru")
    if not mineru_cmd:
        raise RuntimeError(
            "MinerU fallback unavailable. Install with: uv pip install -U \"mineru[all]\" "
            "and ensure 'mineru' is available in PATH."
        )

    with tempfile.TemporaryDirectory(prefix="rucai-mineru-") as tmpdir:
        cmd = [mineru_cmd, "-p", str(pdf_path), "-o", tmpdir, "-b", "pipeline"]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=900,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"MinerU failed: {err[-800:]}")

        md_files = sorted(Path(tmpdir).rglob("*.md"))
        if not md_files:
            return ""

        texts = []
        for md in md_files:
            try:
                content = md.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            cleaned = normalize_text(content)
            if cleaned:
                texts.append(cleaned)
        return "\n\n".join(texts)


def detect_language(text: str) -> str:
    lowered = text.lower()
    danish_markers = [" og ", " det ", " der ", " ikke ", " med ", " til ", " en ", " et "]
    english_markers = [" the ", " and ", " is ", " are ", " with ", " for ", " to ", " of "]

    da_score = sum(lowered.count(m) for m in danish_markers)
    en_score = sum(lowered.count(m) for m in english_markers)
    da_score += lowered.count("æ") + lowered.count("ø") + lowered.count("å")

    if da_score == 0 and en_score == 0:
        return "unknown"
    if da_score >= en_score:
        return "da"
    return "en"


def ingest_pdf(
    pdf_path: Path,
    settings: Settings,
    course_id: int,
    scan_mode: str = "digital",
    progress_cb: Optional[Callable[[int, int], None]] = None,
    min_chars: int = 200,
    max_words: int = 800,
    overlap: int = 100,
    min_ocr_chars: int = 80,
    min_alpha_ratio: float = 0.5,
) -> tuple[int, int]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing PDF: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)

    converter: Optional[DocumentConverter] = None
    chunks_inserted = 0
    prefer_docling = scan_mode == "hand_scanned"
    effective_min_alpha_ratio = 0.35 if prefer_docling else min_alpha_ratio

    with get_connection(settings) as conn:
        doc_id = get_or_create_document(
            conn,
            course_id=course_id,
            path=str(pdf_path),
            filename=pdf_path.name,
            source=str(pdf_path.parent),
        )
        clear_chunks(conn, doc_id)

        chunk_index = 0
        language_samples: list[str] = []
        for page_number in range(1, total_pages + 1):
            raw_text = extract_page_text_pypdf(reader, page_number)
            cleaned = normalize_text(raw_text)

            use_docling = prefer_docling or len(cleaned) < min_chars
            if use_docling:
                if converter is None:
                    converter = DocumentConverter()
                try:
                    docling_text = extract_page_text_docling(
                        converter, pdf_path, page_number
                    )
                    cleaned = normalize_text(docling_text)
                except Exception as exc:
                    logger.warning(
                        "Docling failed on %s page %s: %s", pdf_path, page_number, exc
                    )

            if not cleaned:
                if progress_cb:
                    progress_cb(page_number, total_pages)
                continue
            if len(language_samples) < 6:
                language_samples.append(cleaned[:1500])

            for chunk in iter_nonempty(chunk_text(cleaned, max_words, overlap)):
                if is_ocr_noise(chunk, min_ocr_chars, effective_min_alpha_ratio):
                    continue

                embedding = embed_text(chunk, settings)
                insert_chunk(
                    conn,
                    document_id=doc_id,
                    chunk_index=chunk_index,
                    page_start=page_number,
                    page_end=page_number,
                    section_title=None,
                    content=chunk,
                    embedding=embedding,
                )
                chunk_index += 1
                chunks_inserted += 1

            if progress_cb:
                progress_cb(page_number, total_pages)

        if language_samples:
            detected = detect_language(" ".join(language_samples))
            set_document_language(conn, doc_id, detected)

        if chunks_inserted == 0 and scan_mode == "hand_scanned":
            mineru_text = extract_text_mineru(pdf_path)
            mineru_cleaned = normalize_text(mineru_text)
            if mineru_cleaned:
                if len(language_samples) < 3:
                    language_samples.append(mineru_cleaned[:3000])
                for chunk in iter_nonempty(chunk_text(mineru_cleaned, max_words, overlap)):
                    embedding = embed_text(chunk, settings)
                    insert_chunk(
                        conn,
                        document_id=doc_id,
                        chunk_index=chunk_index,
                        page_start=1,
                        page_end=1,
                        section_title="mineru_fallback",
                        content=chunk,
                        embedding=embedding,
                    )
                    chunk_index += 1
                    chunks_inserted += 1
                detected = detect_language(" ".join(language_samples))
                set_document_language(conn, doc_id, detected)

        if chunks_inserted == 0:
            raise RuntimeError(
                "No extractable text found. "
                "For scanned PDFs: choose hand_scanned and ensure OCR fallback dependencies are installed."
            )

        conn.commit()

    return doc_id, chunks_inserted


def ingest_docx(
    docx_path: Path,
    settings: Settings,
    course_id: int,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    max_words: int = 800,
    overlap: int = 100,
) -> tuple[int, int]:
    if not docx_path.exists():
        raise FileNotFoundError(f"Missing DOCX: {docx_path}")

    document = Document(str(docx_path))
    paragraphs = [normalize_text(p.text) for p in document.paragraphs]
    nonempty = [p for p in paragraphs if p]
    total_units = max(1, len(nonempty))

    with get_connection(settings) as conn:
        doc_id = get_or_create_document(
            conn,
            course_id=course_id,
            path=str(docx_path),
            filename=docx_path.name,
            source=str(docx_path.parent),
        )
        clear_chunks(conn, doc_id)

        chunk_index = 0
        chunks_inserted = 0
        language_samples: list[str] = []
        for idx, text in enumerate(nonempty, start=1):
            if len(language_samples) < 12:
                language_samples.append(text[:1500])
            for chunk in iter_nonempty(chunk_text(text, max_words, overlap)):
                embedding = embed_text(chunk, settings)
                insert_chunk(
                    conn,
                    document_id=doc_id,
                    chunk_index=chunk_index,
                    page_start=idx,
                    page_end=idx,
                    section_title=None,
                    content=chunk,
                    embedding=embedding,
                )
                chunk_index += 1
                chunks_inserted += 1

            if progress_cb:
                progress_cb(idx, total_units)

        if language_samples:
            detected = detect_language(" ".join(language_samples))
            set_document_language(conn, doc_id, detected)

        conn.commit()

    return doc_id, chunks_inserted


def ingest_document(
    input_path: Path,
    settings: Settings,
    course_id: int,
    scan_mode: str = "digital",
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> tuple[int, int]:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        return ingest_pdf(
            pdf_path=input_path,
            settings=settings,
            course_id=course_id,
            scan_mode=scan_mode,
            progress_cb=progress_cb,
        )
    if suffix == ".docx":
        return ingest_docx(
            docx_path=input_path,
            settings=settings,
            course_id=course_id,
            progress_cb=progress_cb,
        )
    raise ValueError(f"Unsupported file type: {input_path.name}")


def process_ingest_job(
    settings: Settings,
    job_id: int,
    course_id: int,
    input_path: Path,
    scan_mode: str = "digital",
) -> None:
    try:
        with get_connection(settings) as conn:
            update_ingest_job(conn, job_id, status="running", progress=0, error=None)
            conn.commit()

        def progress(page: int, total: int) -> None:
            pct = min(99, int((page / max(total, 1)) * 100))
            with get_connection(settings) as conn:
                update_ingest_job(conn, job_id, status="running", progress=pct, error=None)
                conn.commit()

        doc_id, _ = ingest_document(
            input_path=input_path,
            settings=settings,
            course_id=course_id,
            scan_mode=scan_mode,
            progress_cb=progress,
        )

        with get_connection(settings) as conn:
            update_ingest_job(
                conn,
                job_id,
                status="done",
                progress=100,
                error=None,
                document_id=doc_id,
            )
            conn.commit()
    except Exception as exc:
        logger.exception("Ingest job %s failed", job_id)
        with get_connection(settings) as conn:
            update_ingest_job(
                conn,
                job_id,
                status="failed",
                progress=100,
                error=str(exc),
            )
            conn.commit()
