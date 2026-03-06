from app.prompts import compose_system_prompt


def test_compose_system_prompt_danish_teacher():
    out = compose_system_prompt(
        "Undervisningskontekst: test.",
        course_title="Kursus",
        course_description="Beskrivelse",
        audience="teacher",
        language="da",
    )
    assert "Du er RUCAI" in out
    assert "Kursuskontekst:" in out
    assert "Regler (låst)" in out


def test_compose_system_prompt_english_student():
    out = compose_system_prompt(
        "Study context: test.",
        course_title="Course",
        course_description="Description",
        audience="student",
        language="en",
    )
    assert "You are RUCAI" in out
    assert "Course context:" in out
    assert "Rules (locked)" in out
