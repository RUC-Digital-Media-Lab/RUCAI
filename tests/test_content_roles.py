from app.content_roles import classify_chunk_role, looks_like_reference_text


def test_reference_detection_keywords() -> None:
    text = "References\nSmith, J. (2020). Journal of Communication. doi: 10.1/abc"
    assert looks_like_reference_text(text) is True
    assert classify_chunk_role(text) == "reference"


def test_reference_detection_regular_content() -> None:
    text = "Henriksen et al. undersøger hvordan diskurser bevæger sig mellem mediearenaer."
    assert looks_like_reference_text(text) is False
    assert classify_chunk_role(text) == "content"
