from app.chat import (
    _is_followup_query,
    contexts_match_query_document_hint,
    filter_contexts_for_explicit_doc_mention,
    filter_reference_noise,
)


def test_followup_query_detection():
    assert _is_followup_query("Er der andre tekster på pensum, der behandler samme spørgsmål?") is True
    assert _is_followup_query("Hvad siger Henriksen teksten?") is False


def test_filter_reference_noise_prefers_non_reference_chunks():
    contexts = [
        {
            "filename": "Henriksen et al. 2024.pdf",
            "content": "How specific discourses travel from Russian-backed content...",
            "page_start": 19,
        },
        {
            "filename": "Henriksen et al. 2024.pdf",
            "content": "References: Yang (2020); Cer (2018); Smith (2017); Doe (2016)",
            "page_start": 24,
        },
    ]
    out = filter_reference_noise(contexts)
    assert len(out) == 1
    assert "References" not in out[0]["content"]


def test_explicit_doc_mention_filter_keeps_contexts_when_no_match():
    contexts = [
        {
            "filename": "Schulze et al. 2022.pdf",
            "content": "Telegram and dark social...",
            "page_start": 23,
        }
    ]
    out = filter_contexts_for_explicit_doc_mention("Hvad siger Henriksen teksten?", contexts)
    assert out == contexts


def test_contexts_match_query_document_hint():
    contexts = [{"filename": "Henriksen et al. 2024.pdf", "content": "x", "page_start": 1}]
    assert contexts_match_query_document_hint("Hvad siger Henriksen teksten?", contexts) is True
