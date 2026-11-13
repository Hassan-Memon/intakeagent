"""The LangGraph intake graph.

    START -> merge_transcript -> extract -> detect_missing
                                                 |
                       finished? ----no----> ask_next_question -> END  (wait for more speech)
                           |
                          yes
                           v
                        verify      (reference data: RxNorm, ICD-10-CM, sanctions lists)
                           v
                     await_approval  (interrupt: human edits + approves)
                           v
                         export -> END

The graph is invoked once per utterance with the new transcript segments; the checkpointer
keeps the thread's state between invocations. When the user presses "finish" the service
invokes with ``finished=True`` and the graph parks at ``await_approval`` via ``interrupt()``.
``POST /sessions/{id}/approve`` resumes it with ``Command(resume=...)``.

``verify`` attaches suggestions and flags for the reviewer; it never edits the record.

Dependencies (extractor, exporters, protocol store, verifier) are injected so tests can run
the graph fully offline.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from intakeagent.graph.extractors import Extractor
from intakeagent.graph.questions import closer, next_question
from intakeagent.graph.state import IntakeState
from intakeagent.schemas import missing_required, schema_for
from intakeagent.schemas.base import field_specs

Exporter = Callable[[str, dict[str, Any], str], dict[str, Any]]  # (vertical, record, sid)
HintLookup = Callable[[str, str], str | None]  # (vertical, field_name) -> hint
VerifyFn = Callable[[str, dict[str, Any]], dict[str, Any]]  # (vertical, record) -> checks


def merge_transcript(state: IntakeState) -> dict[str, Any]:
    """Join segments into one string, recording each segment's char offset for evidence."""
    segments = state.get("transcript_segments", [])
    parts: list[str] = []
    offset = 0
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        seg["char_start"] = offset
        parts.append(text)
        offset += len(text) + 1
    return {"transcript": " ".join(parts)}


def build_intake_graph(
    extractor: Extractor,
    exporters: dict[str, Exporter] | None = None,
    hint_lookup: HintLookup | None = None,
    verifier: VerifyFn | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    exporters = exporters or {}

    def extract(state: IntakeState) -> dict[str, Any]:
        vertical = state["vertical"]
        schema = schema_for(vertical)  # type: ignore[arg-type]
        previous = schema(**state["record"]) if state.get("record") else None
        record = extractor.extract(state.get("transcript", ""), vertical, previous)
        return {"record": record.model_dump()}

    def detect_missing(state: IntakeState) -> dict[str, Any]:
        schema = schema_for(state["vertical"])  # type: ignore[arg-type]
        record = schema(**state["record"])
        return {"missing_fields": missing_required(record)}

    def route_after_missing(state: IntakeState) -> str:
        return "verify" if state.get("finished") else "ask_next_question"

    def ask_next_question(state: IntakeState) -> dict[str, Any]:
        vertical = state["vertical"]
        specs = field_specs(schema_for(vertical))  # type: ignore[arg-type]
        missing = state.get("missing_fields", [])
        asked = state.get("questions_asked", [])
        hint = None
        if hint_lookup and missing:
            hint = hint_lookup(vertical, missing[0])
        question, field = next_question(specs, missing, asked, hint)
        if question is None:
            question = closer(vertical)
        return {
            "next_question": question,
            "next_field": field,
            "questions_asked": [question],
        }

    def verify(state: IntakeState) -> dict[str, Any]:
        if verifier is None:
            return {"verification": None}
        try:
            return {"verification": verifier(state["vertical"], state["record"])}
        except Exception as exc:  # reference data is advisory; never block review on it
            return {
                "verification": {
                    "vertical": state["vertical"],
                    "flags": [],
                    "sources": [],
                    "errors": [f"verification failed: {exc}"],
                }
            }

    def await_approval(state: IntakeState) -> dict[str, Any]:
        # interrupt() pauses the graph and surfaces this payload to the caller. When resumed,
        # the node re-runs from the top and interrupt() returns the resume value instead.
        decision = interrupt(
            {
                "session_id": state["session_id"],
                "record": state["record"],
                "missing_fields": state.get("missing_fields", []),
                "verification": state.get("verification"),
                "message": "Review the record, edit if needed, then approve.",
            }
        )
        if not decision or not decision.get("approved", False):
            return {"approved": False, "export_target": None}
        record = state["record"]
        edits = decision.get("record") or {}
        if edits:
            schema = schema_for(state["vertical"])  # type: ignore[arg-type]
            record = schema(**edits).model_dump()
        return {
            "approved": True,
            "record": record,
            "export_target": decision.get("export_target"),
            "next_question": closer(state["vertical"]),
        }

    def export(state: IntakeState) -> dict[str, Any]:
        target = state.get("export_target")
        if not state.get("approved") or not target:
            return {"export_result": None}
        fn = exporters.get(target)
        if fn is None:
            return {"export_result": {"error": f"unknown export target: {target}"}}
        return {"export_result": fn(state["vertical"], state["record"], state["session_id"])}

    g = StateGraph(IntakeState)
    g.add_node("merge_transcript", merge_transcript)
    g.add_node("extract", extract)
    g.add_node("detect_missing", detect_missing)
    g.add_node("ask_next_question", ask_next_question)
    g.add_node("verify", verify)
    g.add_node("await_approval", await_approval)
    g.add_node("export", export)

    g.add_edge(START, "merge_transcript")
    g.add_edge("merge_transcript", "extract")
    g.add_edge("extract", "detect_missing")
    g.add_conditional_edges(
        "detect_missing",
        route_after_missing,
        {"ask_next_question": "ask_next_question", "verify": "verify"},
    )
    g.add_edge("ask_next_question", END)
    g.add_edge("verify", "await_approval")
    g.add_edge("await_approval", "export")
    g.add_edge("export", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
