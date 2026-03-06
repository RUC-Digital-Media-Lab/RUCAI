from app.main import _is_teacher_facing_student_query, _student_scope_redirect_answer
from app.prompts import to_student_editable_instructions


def test_student_editable_filters_teacher_didactic_lines():
    teacher_text = """Undervisningskontekst:\n- Lav didaktisk undervisningsplan for uge 3.\n- Hjælp med begrebsafklaring i pensum."""
    out = to_student_editable_instructions(teacher_text)
    assert "lav didaktisk undervisningsplan" not in out.lower()
    assert "undervisningsplan for uge 3" not in out.lower()
    assert "studiestøtte" in out.lower() or "student-policy" in out.lower()


def test_teacher_facing_query_detection():
    assert _is_teacher_facing_student_query("Lav en undervisningsplan for uge 2") is True
    assert _is_teacher_facing_student_query("Forklar hovedargumentet i teksten") is False


def test_student_scope_redirect_language():
    assert "student support" in _student_scope_redirect_answer("en")
    assert "studiestøtte" in _student_scope_redirect_answer("da")


def test_student_editable_english_is_not_mixed_with_danish_policy_text():
    teacher_text = "Teaching context:\n- Help with concept clarification."
    out = to_student_editable_instructions(teacher_text, language="en")
    assert "Student policy (locked for this instance)" in out
    assert "låst for denne instance" not in out
