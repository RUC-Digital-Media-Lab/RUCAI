import app.chat as chat


def test_is_synthesis_query_detects_danish_phrase():
    assert chat._is_synthesis_query("Hvordan hænger pensum sammen?") is True


def test_is_synthesis_query_false_for_narrow_question():
    assert chat._is_synthesis_query("Hvad betyder distributed agency i kapitel 1?") is False


def test_detect_query_intent_compare():
    intent = chat.detect_query_intent("Sammenlign ligheder og forskelle mellem tekst A og B")
    assert intent["intent"] == chat.INTENT_COMPARE
    assert float(intent["confidence"]) >= 0.8


def test_chat_response_synthesis_adds_metadata_and_round_two(monkeypatch):
    def fake_search_chunks(
        query,
        settings,
        top_k,
        course_id,
        *,
        diversify_by_document=False,
        max_per_document=2,
        candidate_multiplier=8,
    ):
        if candidate_multiplier >= 24:
            return [
                {
                    "filename": "a.pdf",
                    "path": "/docs/a.pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "chunk_index": 0,
                    "content": "A",
                    "distance": 0.10,
                },
                {
                    "filename": "b.pdf",
                    "path": "/docs/b.pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "chunk_index": 1,
                    "content": "B",
                    "distance": 0.11,
                },
                {
                    "filename": "c.pdf",
                    "path": "/docs/c.pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "chunk_index": 2,
                    "content": "C",
                    "distance": 0.12,
                },
                {
                    "filename": "d.pdf",
                    "path": "/docs/d.pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "chunk_index": 3,
                    "content": "D",
                    "distance": 0.13,
                },
                {
                    "filename": "e.pdf",
                    "path": "/docs/e.pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "chunk_index": 4,
                    "content": "E",
                    "distance": 0.14,
                },
            ][:top_k]
        return [
            {
                "filename": "a.pdf",
                "path": "/docs/a.pdf",
                "page_start": 1,
                "page_end": 1,
                "chunk_index": 0,
                "content": "A",
                "distance": 0.10,
            },
            {
                "filename": "a.pdf",
                "path": "/docs/a.pdf",
                "page_start": 2,
                "page_end": 2,
                "chunk_index": 1,
                "content": "A2",
                "distance": 0.11,
            },
        ][:top_k]

    monkeypatch.setattr(chat, "search_chunks", fake_search_chunks)
    monkeypatch.setattr(chat, "generate_answer", lambda prompt, settings: "Svar [1]")
    monkeypatch.setattr(chat, "compose_system_prompt", lambda *args, **kwargs: "SYSTEM")

    data = chat.chat_response(
        "Hvordan hænger pensum sammen?",
        settings=None,
        top_k=5,
        course_id=1,
        history=[],
    )
    assert data["intent"] == chat.INTENT_SYNTHESIS
    assert data["retrieval_rounds"] == 2
    assert data["unique_documents"] >= 5
    assert data["source_count"] == len(data["sources"])
    assert data["chunk_count"] == len(data["contexts"])


def test_citations_are_unique_per_document():
    contexts = [
        {
            "filename": "Metodekogebogen.pdf",
            "path": "/docs/metode.pdf",
            "page_start": 10,
            "page_end": 10,
            "chunk_index": 1,
            "content": "A",
            "distance": 0.1,
        },
        {
            "filename": "Metodekogebogen.pdf",
            "path": "/docs/metode.pdf",
            "page_start": 11,
            "page_end": 11,
            "chunk_index": 2,
            "content": "B",
            "distance": 0.2,
        },
        {
            "filename": "Diskursive.pdf",
            "path": "/docs/diskursive.pdf",
            "page_start": 5,
            "page_end": 5,
            "chunk_index": 1,
            "content": "C",
            "distance": 0.3,
        },
    ]
    citations = chat._citations_from_contexts(contexts)
    assert len(citations) == 2
    assert citations[0]["ref"] == 1
    assert citations[1]["ref"] == 2


def test_citations_collapse_timestamp_prefixed_duplicates():
    contexts = [
        {
            "filename": "20260221-212730-Metodekogebogen.pdf",
            "path": "/docs/20260221-212730-Metodekogebogen.pdf",
            "page_start": 13,
            "page_end": 13,
            "chunk_index": 12,
            "content": "Tekst og værk",
            "distance": 0.1,
        },
        {
            "filename": "20260221-212738-Metodekogebogen.pdf",
            "path": "/docs/20260221-212738-Metodekogebogen.pdf",
            "page_start": 13,
            "page_end": 13,
            "chunk_index": 12,
            "content": "Tekst og værk",
            "distance": 0.2,
        },
    ]
    citations = chat._citations_from_contexts(contexts)
    assert len(citations) == 1
    assert citations[0]["ref"] == 1


def test_grouped_sources_count_unique_documents():
    contexts = [
        {
            "filename": "20260221-212730-Metodekogebogen.pdf",
            "path": "/docs/20260221-212730-Metodekogebogen.pdf",
            "page_start": 13,
            "page_end": 13,
            "chunk_index": 12,
            "content": "Tekst og værk",
            "distance": 0.1,
        },
        {
            "filename": "20260221-212738-Metodekogebogen.pdf",
            "path": "/docs/20260221-212738-Metodekogebogen.pdf",
            "page_start": 29,
            "page_end": 29,
            "chunk_index": 28,
            "content": "Denne bog gør det sjovere...",
            "distance": 0.2,
        },
        {
            "filename": "Stjernfelt.pdf",
            "path": "/docs/stjernfelt.pdf",
            "page_start": 2,
            "page_end": 2,
            "chunk_index": 1,
            "content": "Et værk og dets titel...",
            "distance": 0.3,
        },
    ]
    sources = chat.build_grouped_sources(contexts)
    assert len(sources) == 2
    assert len(sources[0]["snippets"]) == 2
