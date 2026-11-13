"""LangGraph state for one intake session.

A ``TypedDict`` with reducers: ``transcript_segments`` and ``questions_asked`` use
``operator.add`` so each new turn appends rather than replaces; every other key is overwritten
by the node that returns it. The checkpointer keys state by ``thread_id`` = session id, so the
graph can be re-invoked once per utterance and still see the full history.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class IntakeState(TypedDict, total=False):
    session_id: str
    vertical: str  # "healthcare" | "legal"

    # Inputs that grow over time.
    transcript_segments: Annotated[list[dict[str, Any]], operator.add]
    questions_asked: Annotated[list[str], operator.add]

    # Derived each turn.
    transcript: str
    record: dict[str, Any]  # PatientIntake / LegalIntake as dict
    missing_fields: list[str]
    next_question: str | None
    next_field: str | None
    redaction_count: int
    verification: dict[str, Any] | None  # reference-data suggestions and flags for review

    # Control flow.
    finished: bool  # user pressed "finish": go to approval instead of asking again
    approved: bool
    export_target: str | None  # "fhir" | "clio" | None
    export_result: dict[str, Any] | None
