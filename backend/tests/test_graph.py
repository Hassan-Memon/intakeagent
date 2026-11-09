"""Graph behaviour: incremental turns, question selection, HITL interrupt and resume."""

from langgraph.types import Command

from intakeagent.graph import build_intake_graph
from intakeagent.graph.extractors import RuleBasedExtractor
from intakeagent.stt.stub import SCRIPTS


def _seg(i: int, text: str) -> dict:
    return {"id": f"s{i}", "text": text, "start_ms": i * 4000, "end_ms": (i + 1) * 4000}


def test_graph_asks_for_first_missing_field_then_progresses():
    graph = build_intake_graph(RuleBasedExtractor())
    cfg = {"configurable": {"thread_id": "t1"}}
    base = {"session_id": "t1", "vertical": "healthcare", "finished": False}

    out = graph.invoke({**base, "transcript_segments": [_seg(0, SCRIPTS["healthcare"][0])]}, cfg)
    assert "full_name" not in out["missing_fields"]
    assert out["next_field"] == "phone"  # first required field still missing
    assert "phone" in out["next_question"].lower()

    out = graph.invoke({**base, "transcript_segments": [_seg(1, SCRIPTS["healthcare"][1])]}, cfg)
    # Both turns are in state thanks to the operator.add reducer.
    assert len(out["transcript_segments"]) == 2
    assert out["record"]["chief_complaint"]["value"]


def test_graph_repeats_softly_when_user_does_not_answer():
    graph = build_intake_graph(RuleBasedExtractor())
    cfg = {"configurable": {"thread_id": "t2"}}
    base = {"session_id": "t2", "vertical": "legal", "finished": False}
    first = graph.invoke({**base, "transcript_segments": [_seg(0, "Hello there.")]}, cfg)
    second = graph.invoke({**base, "transcript_segments": [_seg(1, "Um, okay.")]}, cfg)
    assert first["next_field"] == second["next_field"] == "client_name"
    assert second["next_question"].startswith("Sorry")


def test_finish_interrupts_for_approval_and_resume_exports():
    exported = {}

    def fake_export(vertical, record, session_id):
        exported["record"] = record
        return {"target": "fhir", "mode": "test", "resource_count": 3}

    graph = build_intake_graph(RuleBasedExtractor(), exporters={"fhir": fake_export})
    cfg = {"configurable": {"thread_id": "t3"}}
    segs = [_seg(i, line) for i, line in enumerate(SCRIPTS["healthcare"])]
    graph.invoke(
        {
            "session_id": "t3",
            "vertical": "healthcare",
            "transcript_segments": segs,
            "finished": False,
        },
        cfg,
    )

    out = graph.invoke(
        {"session_id": "t3", "vertical": "healthcare", "transcript_segments": [], "finished": True},
        cfg,
    )
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert payload["missing_fields"] == []
    assert payload["record"]["full_name"]["value"] == "Sarah Mitchell"
    assert "await_approval" in graph.get_state(cfg).next

    edited = dict(payload["record"])
    edited["full_name"] = {**edited["full_name"], "value": "Sarah J. Mitchell"}
    out = graph.invoke(
        Command(resume={"approved": True, "record": edited, "export_target": "fhir"}), cfg
    )
    assert out["approved"] is True
    assert out["record"]["full_name"]["value"] == "Sarah J. Mitchell"
    assert out["export_result"]["resource_count"] == 3
    assert exported["record"]["full_name"]["value"] == "Sarah J. Mitchell"
    assert graph.get_state(cfg).next == ()


def test_rejection_does_not_export():
    graph = build_intake_graph(
        RuleBasedExtractor(), exporters={"clio": lambda v, r, s: {"should": "not run"}}
    )
    cfg = {"configurable": {"thread_id": "t4"}}
    graph.invoke(
        {
            "session_id": "t4",
            "vertical": "legal",
            "transcript_segments": [_seg(0, SCRIPTS["legal"][0])],
            "finished": True,
        },
        cfg,
    )
    out = graph.invoke(Command(resume={"approved": False}), cfg)
    assert out["approved"] is False
    assert out["export_result"] is None


def test_hint_lookup_is_appended_to_question():
    graph = build_intake_graph(
        RuleBasedExtractor(), hint_lookup=lambda vertical, field: f"hint for {field}"
    )
    out = graph.invoke(
        {
            "session_id": "t5",
            "vertical": "healthcare",
            "transcript_segments": [_seg(0, "Hi.")],
            "finished": False,
        },
        {"configurable": {"thread_id": "t5"}},
    )
    assert "hint for full_name" in out["next_question"]
