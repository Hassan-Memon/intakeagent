"""Pick the next question from the missing-field list.

Fields are asked in schema declaration order, which mirrors how a human coordinator works
(identity first, then the reason for the visit, then history, then billing). If the previous
turn asked the same question and the field is still empty we soften the repeat. A short
protocol snippet from the RAG store is appended as a hint so the question reflects the
clinic's or firm's own intake protocol.
"""

from __future__ import annotations

from intakeagent.schemas import FieldSpec

OPENERS = {
    "healthcare": "Hello, I'm the intake assistant. I'll ask a few questions before you see the "
    "clinician. You can speak naturally.",
    "legal": "Hello, I'm the intake assistant for the firm. I'll gather some details so a "
    "lawyer can review your matter. You can speak naturally.",
}

CLOSERS = {
    "healthcare": "Thank you. I have everything I need for now. A member of staff will review "
    "your details before they go into your chart.",
    "legal": "Thank you. I have what I need for a conflict check. A member of the team will "
    "review your details before a matter is opened.",
}


def opener(vertical: str) -> str:
    return OPENERS.get(vertical, OPENERS["healthcare"])


def closer(vertical: str) -> str:
    return CLOSERS.get(vertical, CLOSERS["healthcare"])


def next_question(
    specs: list[FieldSpec],
    missing: list[str],
    asked: list[str],
    hint: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (question, field_name) or (None, None) when nothing is missing."""
    by_name = {s.name: s for s in specs}
    for name in missing:
        spec = by_name.get(name)
        if not spec:
            continue
        question = spec.question
        if asked and asked[-1] == question:
            question = f"Sorry, I did not catch that. {question}"
        if hint:
            question = f"{question} ({hint})"
        return question, name
    return None, None
