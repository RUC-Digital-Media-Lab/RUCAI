from app.ingest import detect_language


def test_detect_language_danish():
    text = "Det er en tekst med danske ord og flere begreber i undervisningen."
    assert detect_language(text) == "da"


def test_detect_language_english():
    text = "This is a sample text with common English words and concepts for teaching."
    assert detect_language(text) == "en"
