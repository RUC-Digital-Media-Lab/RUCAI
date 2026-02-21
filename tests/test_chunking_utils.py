from app.chunking import normalize_text


def test_normalize_text_removes_nul_bytes():
    text = "alpha\x00beta   gamma"
    assert normalize_text(text) == "alpha beta gamma"
