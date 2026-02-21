import re
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
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
) -> str:
    grouped_sources = build_grouped_sources(contexts, max_snippets_per_source=1)
    blocks = []
    for source in grouped_sources:
        ref = int(source["ref"])
        snippets = source.get("snippets") or []
        for snippet in snippets:
            header = f"[{ref}] {snippet.get('filename', source.get('filename', 'ukendt'))} p{snippet.get('page_start', '?')}"
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

    return (
        system_prompt
        + "\n\nSAMTALEHISTORIK:\n"
        + history_text
        + "\n\nKILDER:\n"
        + context_text
        + "\n\nBRUGERSPØRGSMÅL:\n"
        + query
        + breadth_instruction
        + "\n\nSkriv et svar med tydelige kildehenvisninger [1], [2]. Hvis flere tekstuddrag kommer fra samme dokument, brug samme [n]."
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
                "filename": ctx.get("filename"),
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
                    "filename": ctx.get("filename"),
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
                "filename": source.get("filename"),
                "page_start": first_snippet.get("page_start"),
                "chunk_index": first_snippet.get("chunk_index"),
            }
        )
    return citations


def chat_response(
    query: str,
    settings: Settings,
    top_k: int,
    course_id: int,
    editable_instructions: str = DEFAULT_EDITABLE_INSTRUCTIONS,
    course_title: str = "",
    course_description: str = "",
    history: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    conversation = history or []
    intent_info = detect_query_intent(query)
    intent = str(intent_info["intent"])
    profile = _RETRIEVAL_PROFILES.get(intent, _RETRIEVAL_PROFILES[INTENT_NARROW])
    retrieval_k = max(top_k, int(profile["min_top_k"]))
    variants = _build_query_variants(query, intent)
    contexts = _run_retrieval_round(
        query_variants=variants,
        settings=settings,
        course_id=course_id,
        top_k=retrieval_k,
        diversify_by_document=bool(profile["diversify_by_document"]),
        max_per_document=int(profile["max_per_document"]),
        candidate_multiplier=int(profile["candidate_multiplier"]),
    )
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
            top_k=retrieval_k + 4,
            diversify_by_document=True,
            max_per_document=1,
            candidate_multiplier=int(profile["candidate_multiplier"]) + 8,
        )
        contexts = _select_for_profile(
            _dedupe_contexts(contexts + round_two),
            top_k=retrieval_k,
            diversify_by_document=bool(profile["diversify_by_document"]),
            max_per_document=int(profile["max_per_document"]),
        )
        retrieval_rounds = 2
        unique_docs = _distinct_doc_count(contexts)

    system_prompt = compose_system_prompt(
        editable_instructions,
        course_title=course_title,
        course_description=course_description,
    )
    grouped_sources = build_grouped_sources(contexts, max_snippets_per_source=3)
    source_count = len(grouped_sources)
    chunk_count = len(contexts)
    required_min_refs = 0
    required_cap = int(profile["required_min_refs_cap"])
    if required_cap > 0 and source_count > 0:
        required_min_refs = min(required_cap, source_count)

    if not contexts:
        answer = (
            "Jeg kan ikke svare fagligt sikkert ud fra det aktuelle materiale. "
            "Prøv at omformulere spørgsmålet eller upload flere relevante tekster."
        )
        prompt = build_prompt(query, contexts, system_prompt, conversation, required_min_refs=required_min_refs)
    else:
        prompt = build_prompt(query, contexts, system_prompt, conversation, required_min_refs=required_min_refs)
        answer = generate_answer(prompt, settings)
    return {
        "query": query,
        "k": retrieval_k,
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
        "prompt": prompt,
    }
