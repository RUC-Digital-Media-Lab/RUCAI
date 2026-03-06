import re
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .content_roles import looks_like_reference_text
from .llm import generate_answer
from .prompts import compose_system_prompt, DEFAULT_EDITABLE_INSTRUCTIONS
from .search import search_chunks

INTENT_NARROW = "narrow"
INTENT_SYNTHESIS = "synthesis"
INTENT_COMPARE = "compare"

_SYNTHESIS_MARKERS = [
    " hvordan hænger ",
    " hænger pensum ",
    " samlet overblik ",
    " på tværs ",
    " sammenhæng i pensum ",
    " hvad er der i pensum ",
    " hvad handler pensum om ",
    " overblik over pensum ",
    " tværgående ",
    " compare the curriculum ",
    " how does the curriculum fit together ",
    " across the texts ",
    " overall synthesis ",
]

_COMPARE_MARKERS = [
    " sammenlign ",
    " compare ",
    " forskelle ",
    " ligheder ",
    " versus ",
    " vs ",
    " hold op imod ",
]

_RETRIEVAL_PROFILES: Dict[str, Dict[str, Any]] = {
    INTENT_NARROW: {
        "min_top_k": 5,
        "candidate_multiplier": 8,
        "diversify_by_document": False,
        "max_per_document": 2,
        "target_unique_docs": 2,
        "required_min_refs_cap": 0,
    },
    INTENT_SYNTHESIS: {
        "min_top_k": 12,
        "candidate_multiplier": 16,
        "diversify_by_document": True,
        "max_per_document": 1,
        "target_unique_docs": 5,
        "required_min_refs_cap": 5,
    },
    INTENT_COMPARE: {
        "min_top_k": 10,
        "candidate_multiplier": 14,
        "diversify_by_document": True,
        "max_per_document": 1,
        "target_unique_docs": 4,
        "required_min_refs_cap": 4,
    },
}

_DOC_TOKEN_STOPWORDS = {
    "tekst",
    "teksten",
    "article",
    "kapitel",
    "chapter",
    "paper",
    "rapport",
    "report",
    "pdf",
    "docx",
    "et",
    "al",
    "teksten",
    "tekstens",
    "siger",
    "about",
    "says",
    "hvad",
    "hvordan",
    "hvorfor",
    "what",
    "which",
    "when",
}

_FOLLOWUP_MARKERS = [
    " andre tekster ",
    " samme spørgsmål ",
    " også ",
    "what about",
    "other texts",
    "same question",
    "do other texts",
]


def _query_doc_tokens(query: str) -> set[str]:
    return {
        t
        for t in re.split(r"[^a-z0-9æøå]+", _normalize_query(query))
        if len(t) >= 4 and t not in _DOC_TOKEN_STOPWORDS
    }


def _has_explicit_doc_hint(query: str) -> bool:
    return bool(
        re.search(
            r"\b(teksten|tekstens|text|article|artiklen|chapter|kapitel)\b",
            _normalize_query(query),
        )
    )


def query_document_tokens(query: str) -> set[str]:
    return _query_doc_tokens(query)


def has_explicit_document_hint(query: str) -> bool:
    return _has_explicit_doc_hint(query)


def _is_synthesis_query(query: str) -> bool:
    return bool(detect_query_intent(query)["intent"] == INTENT_SYNTHESIS)


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def detect_query_intent(query: str) -> Dict[str, object]:
    q = f" {_normalize_query(query)} "
    if not q.strip():
        return {"intent": INTENT_NARROW, "confidence": 0.5, "signals": ["empty_query_default"]}

    synthesis_score = 0.0
    compare_score = 0.0
    signals: List[str] = []

    if any(marker in q for marker in _SYNTHESIS_MARKERS):
        synthesis_score += 0.8
        signals.append("synthesis_phrase_match")

    if any(marker in q for marker in _COMPARE_MARKERS):
        compare_score += 0.8
        signals.append("compare_phrase_match")

    token_count = len(re.findall(r"\w+", q))
    if token_count >= 12:
        synthesis_score += 0.1
        signals.append("long_query")

    broad_words = ["pensum", "overblik", "tværs", "samlet", "sammenhæng", "helhed", "overall"]
    broad_hits = sum(1 for w in broad_words if f" {w} " in q)
    if broad_hits >= 2:
        synthesis_score += 0.15
        signals.append("broad_terms")
    elif broad_hits == 1:
        synthesis_score += 0.08

    compare_words = ["sammenlign", "forskelle", "ligheder", "versus", "vs", "compare"]
    compare_hits = sum(1 for w in compare_words if f" {w} " in q)
    if compare_hits >= 2:
        compare_score += 0.15
        signals.append("compare_terms")
    elif compare_hits == 1:
        compare_score += 0.08

    if compare_score >= 0.8:
        return {"intent": INTENT_COMPARE, "confidence": min(1.0, compare_score), "signals": signals}
    if synthesis_score >= 0.8:
        return {"intent": INTENT_SYNTHESIS, "confidence": min(1.0, synthesis_score), "signals": signals}
    return {
        "intent": INTENT_NARROW,
        "confidence": max(0.5, min(0.79, max(synthesis_score, compare_score))),
        "signals": signals or ["default_narrow"],
    }


def _distinct_doc_count(contexts: List[Dict[str, object]]) -> int:
    keys = {_canonical_document_key(c) for c in contexts if _canonical_document_key(c)}
    return len(keys)


def _normalize_filename_for_grouping(filename: str) -> str:
    name = str(filename or "").strip()
    # Remove upload timestamp prefix, e.g. 20260221-212730-MyDoc.pdf -> MyDoc.pdf
    name = re.sub(r"^\d{8}-\d{6}-", "", name)
    return name.lower()


def _display_filename(filename: str) -> str:
    name = str(filename or "").strip()
    return re.sub(r"^\d{8}-\d{6}-", "", name)


def _doc_tokens_from_filename(filename: str) -> set[str]:
    base = _display_filename(filename).lower()
    base = re.sub(r"\.(pdf|docx)$", "", base)
    tokens = {t for t in re.split(r"[^a-z0-9æøå]+", base) if len(t) >= 4}
    return {t for t in tokens if t not in _DOC_TOKEN_STOPWORDS}


def filter_contexts_for_explicit_doc_mention(
    query: str,
    contexts: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    q = f" {_normalize_query(query)} "
    if not q.strip() or not contexts:
        return contexts

    query_tokens = _query_doc_tokens(query)
    explicit_doc_hint = _has_explicit_doc_hint(query)
    if not query_tokens:
        return contexts

    matched_keys: set[str] = set()
    for item in contexts:
        doc_key = _canonical_document_key(item)
        if not doc_key:
            continue
        filename = str(item.get("filename") or "")
        filename_tokens = _doc_tokens_from_filename(filename)
        if filename_tokens.intersection(query_tokens):
            matched_keys.add(doc_key)

    if not matched_keys:
        # Let caller run a targeted retrieval fallback before failing hard.
        if explicit_doc_hint:
            return contexts
        return contexts

    narrowed = [c for c in contexts if _canonical_document_key(c) in matched_keys]
    return narrowed or contexts


def contexts_match_query_document_hint(query: str, contexts: List[Dict[str, object]]) -> bool:
    tokens = _query_doc_tokens(query)
    if not tokens or not contexts:
        return False
    for item in contexts:
        filename_tokens = _doc_tokens_from_filename(str(item.get("filename") or ""))
        if filename_tokens.intersection(tokens):
            return True
    return False


def _canonical_document_key(ctx: Dict[str, object]) -> str:
    filename = str(ctx.get("filename") or "").strip()
    if filename:
        return _normalize_filename_for_grouping(filename)
    path = str(ctx.get("path") or "").strip()
    if path:
        return _normalize_filename_for_grouping(path.split("/")[-1])
    return ""


def _normalize_content_for_fingerprint(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return compact[:280]


def _is_followup_query(query: str) -> bool:
    q = f" {_normalize_query(query)} "
    if not q.strip():
        return False
    return any(marker in q for marker in _FOLLOWUP_MARKERS)


def _last_user_message(history: List[Dict[str, object]]) -> str:
    for item in reversed(history):
        if str(item.get("role") or "").lower() == "user":
            msg = str(item.get("content") or "").strip()
            if msg:
                return msg
    return ""


def _looks_like_reference_chunk(content: str) -> bool:
    return looks_like_reference_text(content)


def filter_reference_noise(contexts: List[Dict[str, object]]) -> List[Dict[str, object]]:
    if not contexts:
        return contexts
    non_ref = [c for c in contexts if not _looks_like_reference_chunk(str(c.get("content") or ""))]
    # Keep refs only if everything looks like refs.
    return non_ref or contexts


def _dedupe_contexts(contexts: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen: set[Tuple[str, int, str]] = set()
    out: List[Dict[str, object]] = []
    for item in sorted(
        contexts,
        key=lambda c: float(c.get("distance")) if c.get("distance") is not None else 9999.0,
    ):
        doc_key = _canonical_document_key(item)
        page = int(item.get("page_start") or 0)
        fingerprint = _normalize_content_for_fingerprint(str(item.get("content") or ""))
        key = (
            doc_key,
            page,
            fingerprint,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _select_for_profile(
    contexts: List[Dict[str, object]],
    *,
    top_k: int,
    diversify_by_document: bool,
    max_per_document: int,
) -> List[Dict[str, object]]:
    if not diversify_by_document:
        return contexts[:top_k]

    per_doc_used: Dict[str, int] = {}
    selected: List[Dict[str, object]] = []
    for item in contexts:
        doc_key = _canonical_document_key(item)
        used = per_doc_used.get(doc_key, 0)
        if used >= max(1, max_per_document):
            continue
        selected.append(item)
        per_doc_used[doc_key] = used + 1
        if len(selected) >= top_k:
            break

    if len(selected) < top_k:
        selected_ids = {id(x) for x in selected}
        for item in contexts:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= top_k:
                break
    return selected


def select_source_first_contexts(
    contexts: List[Dict[str, object]],
    *,
    target_sources: int,
    max_chunks_per_source: int = 3,
) -> List[Dict[str, object]]:
    target = max(1, int(target_sources))
    per_source_cap = max(1, int(max_chunks_per_source))
    deduped = _dedupe_contexts(contexts)

    selected: List[Dict[str, object]] = []
    selected_ids: set[int] = set()
    selected_sources: set[str] = set()
    per_source_count: Dict[str, int] = {}

    # Pass 1: pick best chunk from each source until source target is reached.
    for item in deduped:
        source_key = _canonical_document_key(item)
        if not source_key or source_key in selected_sources:
            continue
        selected.append(item)
        selected_ids.add(id(item))
        selected_sources.add(source_key)
        per_source_count[source_key] = 1
        if len(selected_sources) >= target:
            break

    # Pass 2: add more chunks from already selected sources.
    for item in deduped:
        if id(item) in selected_ids:
            continue
        source_key = _canonical_document_key(item)
        if not source_key or source_key not in selected_sources:
            continue
        used = per_source_count.get(source_key, 0)
        if used >= per_source_cap:
            continue
        selected.append(item)
        per_source_count[source_key] = used + 1

    if not selected:
        return deduped[:target]
    return selected


def _build_query_variants(query: str, intent: str) -> List[str]:
    variants = [query.strip()]
    if intent == INTENT_SYNTHESIS:
        variants.append(f"{query.strip()} på tværs af alle tekster i pensum")
        variants.append("samlet overblik over pensum og centrale sammenhænge")
    elif intent == INTENT_COMPARE:
        variants.append(f"sammenlign centrale ligheder og forskelle: {query.strip()}")
        variants.append(f"{query.strip()} hold teksterne op imod hinanden")

    out: List[str] = []
    seen: set[str] = set()
    for v in variants:
        clean = " ".join(v.split())
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _run_retrieval_round(
    *,
    query_variants: List[str],
    settings: Settings,
    course_id: int,
    top_k: int,
    diversify_by_document: bool,
    max_per_document: int,
    candidate_multiplier: int,
    include_reference_chunks: bool = False,
    filename_tokens: Optional[List[str]] = None,
) -> List[Dict[str, object]]:
    merged: List[Dict[str, object]] = []
    for q in query_variants:
        rows = search_chunks(
            q,
            settings,
            top_k,
            course_id,
            diversify_by_document=diversify_by_document,
            max_per_document=max_per_document,
            candidate_multiplier=candidate_multiplier,
            include_reference_chunks=include_reference_chunks,
            filename_tokens=filename_tokens,
        )
        merged.extend(rows)
    deduped = _dedupe_contexts(merged)
    return _select_for_profile(
        deduped,
        top_k=top_k,
        diversify_by_document=diversify_by_document,
        max_per_document=max_per_document,
    )


def _format_history(history: List[Dict[str, object]]) -> str:
    if not history:
        return "Ingen tidligere beskeder."
    lines: List[str] = []
    for item in history:
        role = str(item.get("role", "user")).upper()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "Ingen tidligere beskeder."


def build_prompt(
    query: str,
    contexts: List[Dict[str, object]],
    system_prompt: str,
    history: List[Dict[str, object]],
    required_min_refs: int = 0,
    language: str = "da",
) -> str:
    grouped_sources = build_grouped_sources(contexts, max_snippets_per_source=1)
    blocks = []
    allowed_sources = []
    for source in grouped_sources:
        ref = int(source["ref"])
        allowed_sources.append(f"[{ref}] {source.get('filename', 'ukendt')}")
        snippets = source.get("snippets") or []
        for snippet in snippets:
            header = f"[{ref}] {_display_filename(str(snippet.get('filename', source.get('filename', 'ukendt'))))} p{snippet.get('page_start', '?')}"
            blocks.append(f"{header}\n{snippet.get('content', '')}")

    context_text = "\n\n".join(blocks)
    history_text = _format_history(history)
    breadth_instruction = ""
    if required_min_refs > 0:
        breadth_instruction = (
            "\n\nKRAV TIL KILDEBREDDE:\n"
            f"- Dette er et bredt/syntetisk spørgsmål. Brug mindst {required_min_refs} forskellige kilder fra KILDER-listen.\n"
            "- Marker kilder løbende med [n].\n"
            "- Hvis du ikke kan nå kravet fagligt forsvarligt, forklar kort hvorfor."
        )

    final_instruction = (
        "\n\nWrite the answer in English with clear source citations [1], [2]. "
        "If multiple excerpts come from the same document, use the same [n]. "
        "Use ONLY the allowed uploaded sources listed under ALLOWED SOURCES. "
        "Do NOT introduce external literature, author-year references, DOI citations, or a separate bibliography section."
        if language == "en"
        else "\n\nSkriv et svar med tydelige kildehenvisninger [1], [2]. "
        "Hvis flere tekstuddrag kommer fra samme dokument, brug samme [n]. "
        "Brug KUN de tilladte uploadede kilder under TILLADTE KILDER. "
        "Indfør ikke ekstern litteratur, forfatter-år referencer, DOI-citater eller en separat bibliografi."
    )

    return (
        system_prompt
        + "\n\nSAMTALEHISTORIK:\n"
        + history_text
        + "\n\nTILLADTE KILDER:\n"
        + ("\n".join(allowed_sources) if allowed_sources else "(ingen)")
        + "\n\nKILDER:\n"
        + context_text
        + "\n\nBRUGERSPØRGSMÅL:\n"
        + query
        + breadth_instruction
        + final_instruction
    )


def build_grouped_sources(
    contexts: List[Dict[str, object]],
    *,
    max_snippets_per_source: int = 3,
) -> List[Dict[str, object]]:
    refs: Dict[str, int] = {}
    next_ref = 1
    grouped: Dict[str, Dict[str, object]] = {}
    ordered: List[str] = []
    per_source_seen: Dict[str, set[Tuple[int, str]]] = {}

    for ctx in contexts:
        key = _canonical_document_key(ctx)
        if not key:
            continue
        if key not in refs:
            refs[key] = next_ref
            next_ref += 1
        if key not in grouped:
            grouped[key] = {
                "ref": refs[key],
                "source_key": key,
                "filename": _display_filename(str(ctx.get("filename") or "")),
                "path": ctx.get("path"),
                "snippets": [],
            }
            per_source_seen[key] = set()
            ordered.append(key)

        snippet_fingerprint = _normalize_content_for_fingerprint(str(ctx.get("content") or ""))
        snippet_key = (int(ctx.get("page_start") or 0), snippet_fingerprint)
        if snippet_key in per_source_seen[key]:
            continue
        per_source_seen[key].add(snippet_key)

        snippets = grouped[key]["snippets"]
        if isinstance(snippets, list) and len(snippets) < max(1, max_snippets_per_source):
            snippets.append(
                {
                    "filename": _display_filename(str(ctx.get("filename") or "")),
                    "page_start": ctx.get("page_start"),
                    "page_end": ctx.get("page_end"),
                    "chunk_index": ctx.get("chunk_index"),
                    "content": ctx.get("content"),
                    "distance": ctx.get("distance"),
                }
            )

    return [grouped[key] for key in ordered]


def _citations_from_contexts(contexts: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped_sources = build_grouped_sources(contexts, max_snippets_per_source=1)
    citations: List[Dict[str, object]] = []
    for source in grouped_sources:
        first_snippet = (source.get("snippets") or [{}])[0]
        citations.append(
            {
                "ref": source.get("ref"),
                "filename": _display_filename(str(source.get("filename") or "")),
                "page_start": first_snippet.get("page_start"),
                "chunk_index": first_snippet.get("chunk_index"),
            }
        )
    return citations


def _reference_mentions_from_contexts(contexts: List[Dict[str, object]], limit: int = 6) -> List[Dict[str, object]]:
    grouped = build_grouped_sources(contexts, max_snippets_per_source=2)
    out: List[Dict[str, object]] = []
    for source in grouped:
        for snippet in source.get("snippets") or []:
            if len(out) >= max(1, limit):
                return out
            out.append(
                {
                    "ref": source.get("ref"),
                    "filename": _display_filename(str(source.get("filename") or "")),
                    "page_start": snippet.get("page_start"),
                    "content": snippet.get("content"),
                }
            )
    return out


def chat_response(
    query: str,
    settings: Settings,
    top_k: int,
    course_id: int,
    editable_instructions: str = DEFAULT_EDITABLE_INSTRUCTIONS,
    course_title: str = "",
    course_description: str = "",
    history: Optional[List[Dict[str, object]]] = None,
    language: str = "da",
) -> Dict[str, object]:
    conversation = history or []
    intent_info = detect_query_intent(query)
    intent = str(intent_info["intent"])
    profile = _RETRIEVAL_PROFILES.get(intent, _RETRIEVAL_PROFILES[INTENT_NARROW])
    requested_sources = max(1, int(top_k))
    retrieval_k = max(requested_sources, int(profile["min_top_k"]))
    initial_candidate_k = max(retrieval_k, requested_sources * 3)
    variants = _build_query_variants(query, intent)
    if _is_followup_query(query):
        anchor = _last_user_message(conversation)
        if anchor:
            anchored = f"{anchor.strip()} | {query.strip()}"
            variants = [anchored] + [v for v in variants if v != anchored]
    contexts = _run_retrieval_round(
        query_variants=variants,
        settings=settings,
        course_id=course_id,
        top_k=initial_candidate_k,
        diversify_by_document=bool(profile["diversify_by_document"]),
        max_per_document=int(profile["max_per_document"]),
        candidate_multiplier=int(profile["candidate_multiplier"]),
        include_reference_chunks=False,
    )
    per_source_chunk_cap = 3 if intent in {INTENT_SYNTHESIS, INTENT_COMPARE} else 2
    contexts = select_source_first_contexts(
        contexts,
        target_sources=requested_sources,
        max_chunks_per_source=per_source_chunk_cap,
    )
    contexts = filter_reference_noise(contexts)
    contexts = filter_contexts_for_explicit_doc_mention(query, contexts)
    explicit_doc_tokens = _query_doc_tokens(query)
    explicit_doc_hint = _has_explicit_doc_hint(query)
    if explicit_doc_hint and explicit_doc_tokens and not contexts_match_query_document_hint(query, contexts):
        targeted = _run_retrieval_round(
            query_variants=variants,
            settings=settings,
            course_id=course_id,
            top_k=max(initial_candidate_k + 6, requested_sources * 4),
            diversify_by_document=True,
            max_per_document=max(1, int(profile["max_per_document"])),
            candidate_multiplier=int(profile["candidate_multiplier"]) + 4,
            include_reference_chunks=False,
            filename_tokens=sorted(explicit_doc_tokens),
        )
        targeted = select_source_first_contexts(
            targeted,
            target_sources=requested_sources,
            max_chunks_per_source=per_source_chunk_cap,
        )
        targeted = filter_reference_noise(targeted)
        targeted = filter_contexts_for_explicit_doc_mention(query, targeted)
        if targeted:
            contexts = targeted
    retrieval_rounds = 1

    unique_docs = _distinct_doc_count(contexts)
    target_unique_docs = int(profile["target_unique_docs"])
    if intent in {INTENT_SYNTHESIS, INTENT_COMPARE} and unique_docs < target_unique_docs:
        fallback_variants = _build_query_variants(
            f"{query.strip()} samlet overblik på tværs",
            intent,
        )
        combined_variants = []
        for v in variants + fallback_variants:
            if v not in combined_variants:
                combined_variants.append(v)
        round_two = _run_retrieval_round(
            query_variants=combined_variants,
            settings=settings,
            course_id=course_id,
            top_k=max(initial_candidate_k + 6, requested_sources * 4),
            diversify_by_document=True,
            max_per_document=1,
            candidate_multiplier=int(profile["candidate_multiplier"]) + 8,
            include_reference_chunks=False,
        )
        contexts = select_source_first_contexts(
            _dedupe_contexts(contexts + round_two),
            target_sources=requested_sources,
            max_chunks_per_source=per_source_chunk_cap,
        )
        contexts = filter_reference_noise(contexts)
        contexts = filter_contexts_for_explicit_doc_mention(query, contexts)
        retrieval_rounds = 2
        unique_docs = _distinct_doc_count(contexts)

    system_prompt = compose_system_prompt(
        editable_instructions,
        course_title=course_title,
        course_description=course_description,
        language="en" if language == "en" else "da",
    )
    grouped_sources = build_grouped_sources(contexts, max_snippets_per_source=3)
    reference_raw = _run_retrieval_round(
        query_variants=variants,
        settings=settings,
        course_id=course_id,
        top_k=min(max(requested_sources * 2, 4), 12),
        diversify_by_document=True,
        max_per_document=1,
        candidate_multiplier=max(6, int(profile["candidate_multiplier"]) // 2),
        include_reference_chunks=True,
    )
    reference_mentions = _reference_mentions_from_contexts(reference_raw, limit=8)
    source_count = len(grouped_sources)
    chunk_count = len(contexts)
    required_min_refs = 0
    required_cap = int(profile["required_min_refs_cap"])
    if required_cap > 0 and source_count > 0:
        required_min_refs = min(required_cap, source_count)

    if not contexts:
        answer = (
            "I cannot answer confidently from the currently available material. "
            "Please rephrase the question or upload more relevant texts."
            if language == "en"
            else "Jeg kan ikke svare fagligt sikkert ud fra det aktuelle materiale. "
            "Prøv at omformulere spørgsmålet eller upload flere relevante tekster."
        )
        prompt = build_prompt(
            query,
            contexts,
            system_prompt,
            conversation,
            required_min_refs=required_min_refs,
            language=language,
        )
    else:
        prompt = build_prompt(
            query,
            contexts,
            system_prompt,
            conversation,
            required_min_refs=required_min_refs,
            language=language,
        )
        answer = generate_answer(prompt, settings)
    return {
        "query": query,
        "k": requested_sources,
        "intent": intent,
        "intent_confidence": float(intent_info.get("confidence") or 0.0),
        "intent_signals": list(intent_info.get("signals") or []),
        "retrieval_rounds": retrieval_rounds,
        "unique_documents": source_count,
        "answer": answer,
        "contexts": contexts,
        "sources": grouped_sources,
        "citations": _citations_from_contexts(contexts),
        "source_count": source_count,
        "chunk_count": chunk_count,
        "reference_mentions": reference_mentions,
        "prompt": prompt,
    }
