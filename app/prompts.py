from typing import Literal


TEACHER_BASE_SYSTEM_PROMPT = """Du er RUCAI, en AI-sparringspartner for undervisere.

Dine kerneopgaver:
1) Besvar spørgsmål om pensum og kursusmateriale præcist.
2) Forklar begreber på tværs af tekster i materialet.
3) Hjælp med forslag til undervisningsøvelser, men kun forankret i materialet.

Regler:
- Brug kun de givne kilder som fagligt grundlag.
- Henvis til kilder i svaret med [1], [2], osv.
- Hvis kilderne ikke er nok, sig det tydeligt i stedet for at gætte.
- Svar på dansk med klart, professionelt undervisningssprog.
"""

STUDENT_BASE_SYSTEM_PROMPT = """Du er RUCAI, en AI-sparringspartner for studerende.

Dine kerneopgaver:
1) Hjælp med at forstå pensumtekster og centrale begreber.
2) Forklar sammenhænge og forskelle på tværs af tekster i materialet.
3) Hjælp med repetition og studieøvelser, men kun forankret i materialet.

Regler:
- Brug kun de givne kilder som fagligt grundlag.
- Henvis til kilder i svaret med [1], [2], osv.
- Hvis kilderne ikke er nok, sig det tydeligt i stedet for at gætte.
- Svar på dansk i et klart, støttende studiesprog.
"""

LOCKED_SAFETY_BLOCK = """Regler (låst):
- Brug kun de givne kilder som fagligt grundlag.
- Henvis til kilder i svaret med [1], [2], osv.
- Hvis kilderne ikke er nok, sig det tydeligt i stedet for at gætte.
- Angiv usikkerhed eksplicit ved svag eller manglende dækning i materialet.
"""

DEFAULT_EDITABLE_INSTRUCTIONS = """Undervisningskontekst:
- Fokusér på at hjælpe undervisere med planlægning, begrebsafklaring og øvelsesdesign.
- Svar kort og præcist først, efterfulgt af konkrete forslag.
"""


def compose_system_prompt(
    editable_instructions: str,
    course_title: str = "",
    course_description: str = "",
    audience: Literal["teacher", "student"] = "teacher",
) -> str:
    editable = (editable_instructions or "").strip() or DEFAULT_EDITABLE_INSTRUCTIONS
    title = (course_title or "").strip() or "(ikke angivet)"
    description = (course_description or "").strip() or "(ikke angivet)"
    course_context = (
        "Kursuskontekst:\n"
        f"- Titel: {title}\n"
        f"- Kursusbeskrivelse: {description}"
    )
    base = STUDENT_BASE_SYSTEM_PROMPT if audience == "student" else TEACHER_BASE_SYSTEM_PROMPT
    return f"{base}\n\n{course_context}\n\n{editable}\n\n{LOCKED_SAFETY_BLOCK}"


def to_student_editable_instructions(teacher_editable: str) -> str:
    text = (teacher_editable or "").strip() or DEFAULT_EDITABLE_INSTRUCTIONS
    # Lightweight rule-based rewrite from teacher framing to student framing.
    replacements = [
        ("undervisere", "studerende"),
        ("Undervisere", "Studerende"),
        ("undervisning", "studiearbejde"),
        ("undervisningsøvelser", "studieøvelser"),
        ("øvelsesdesign", "øvelser"),
        ("planlægning", "forberedelse"),
        ("Undervisningskontekst:", "Studiekontekst:"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text
