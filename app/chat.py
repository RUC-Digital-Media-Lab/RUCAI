from typing import Dict, List, Optional

from .config import Settings
from .llm import generate_answer
from .prompts import compose_system_prompt, DEFAULT_EDITABLE_INSTRUCTIONS
from .search import search_chunks


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
) -> str:
    blocks = []
    for idx, ctx in enumerate(contexts, start=1):
        header = f"[{idx}] {ctx['filename']} p{ctx['page_start']}"
        blocks.append(f"{header}\n{ctx['content']}")

    context_text = "\n\n".join(blocks)
    history_text = _format_history(history)
    return (
        system_prompt
        + "\n\nSAMTALEHISTORIK:\n"
        + history_text
        + "\n\nKILDER:\n"
        + context_text
        + "\n\nBRUGERSPØRGSMÅL:\n"
        + query
        + "\n\nSkriv et svar med tydelige kildehenvisninger [1], [2]."
    )


def _citations_from_contexts(contexts: List[Dict[str, object]]) -> List[Dict[str, object]]:
    citations: List[Dict[str, object]] = []
    for idx, ctx in enumerate(contexts, start=1):
        citations.append(
            {
                "ref": idx,
                "filename": ctx["filename"],
                "page_start": ctx["page_start"],
                "chunk_index": ctx["chunk_index"],
            }
        )
    return citations


def chat_response(
    query: str,
    settings: Settings,
    top_k: int,
    course_id: int,
    editable_instructions: str = DEFAULT_EDITABLE_INSTRUCTIONS,
    history: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    conversation = history or []
    contexts = search_chunks(query, settings, top_k, course_id)
    system_prompt = compose_system_prompt(editable_instructions)
    if not contexts:
        answer = (
            "Jeg kan ikke svare fagligt sikkert ud fra det aktuelle materiale. "
            "Prøv at omformulere spørgsmålet eller upload flere relevante tekster."
        )
        prompt = build_prompt(query, contexts, system_prompt, conversation)
    else:
        prompt = build_prompt(query, contexts, system_prompt, conversation)
        answer = generate_answer(prompt, settings)
    return {
        "query": query,
        "k": top_k,
        "answer": answer,
        "contexts": contexts,
        "citations": _citations_from_contexts(contexts),
        "source_count": len(contexts),
        "prompt": prompt,
    }
