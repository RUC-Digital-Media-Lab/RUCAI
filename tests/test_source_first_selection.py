from app.chat import filter_contexts_for_explicit_doc_mention, select_source_first_contexts


def test_select_source_first_contexts_prefers_distinct_sources_before_extra_chunks():
    contexts = [
        {"filename": "A.pdf", "page_start": 1, "content": "a1", "distance": 0.01},
        {"filename": "A.pdf", "page_start": 2, "content": "a2", "distance": 0.02},
        {"filename": "B.pdf", "page_start": 1, "content": "b1", "distance": 0.03},
        {"filename": "C.pdf", "page_start": 1, "content": "c1", "distance": 0.04},
    ]

    selected = select_source_first_contexts(contexts, target_sources=2, max_chunks_per_source=2)
    filenames = [x["filename"] for x in selected]

    assert "A.pdf" in filenames
    assert "B.pdf" in filenames
    assert filenames.count("A.pdf") <= 2


def test_filter_contexts_for_explicit_doc_mention_narrows_to_named_text():
    contexts = [
        {"filename": "Henriksen et al. 2024.pdf", "page_start": 1, "content": "h", "distance": 0.01},
        {"filename": "Papacharissi 2016.pdf", "page_start": 1, "content": "p", "distance": 0.02},
    ]
    narrowed = filter_contexts_for_explicit_doc_mention("Hvad siger Henriksen teksten?", contexts)
    assert len(narrowed) == 1
    assert narrowed[0]["filename"] == "Henriksen et al. 2024.pdf"
