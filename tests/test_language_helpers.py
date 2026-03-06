from app.main import _detect_message_language, _effective_language, _normalize_language


def test_effective_language_prefers_answer_override():
    assert _effective_language("da", "en") == "en"
    assert _effective_language("en", "da") == "da"


def test_effective_language_falls_back_to_ui_language():
    assert _effective_language("en", None) == "en"
    assert _effective_language("da", None) == "da"


def test_effective_language_default_is_danish():
    assert _effective_language(None, None) == "da"
    assert _effective_language("xx", "yy") == "da"  # type: ignore[arg-type]


def test_normalize_language():
    assert _normalize_language("en") == "en"
    assert _normalize_language("da") == "da"
    assert _normalize_language(None) == "da"


def test_detect_message_language_short_danish_query():
    assert _detect_message_language("Hvad siger Henriksen teksten?") == "da"
