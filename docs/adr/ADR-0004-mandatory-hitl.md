# ADR-0004: Mandatory human approval via LangGraph interrupt

- Status: accepted
- Date: 2026-11-09
- Deciders: Hassan Memon

## Context and problem statement

An intake record becomes part of a medical chart or a legal matter. Errors propagate: a
wrong allergy or a missed conflict-check name has real consequences. Extraction, whether by
rules or an LLM, will sometimes be wrong. Where does human judgement enter, and how do we make
it impossible to skip?

## Decision drivers

- Liability sits with the clinic or firm, so they must own the final record.
- Buyers trust a system whose safety property is structural rather than a toggle.
- The review step should be fast: show evidence, highlight gaps, allow edits in place.
- The approval must survive the user leaving and coming back later.

## Considered options

1. Auto-export when confidence exceeds a threshold; review only low-confidence records.
2. Review as a UI-only step; the backend exports whatever it is asked to.
3. Approval as a graph node that pauses execution with `interrupt()`; the only edge into
   `export` comes from that node; resume carries the edited record.

## Decision outcome

Chosen option 3. In `backend/intakeagent/graph/builder.py` the graph is

    merge_transcript -> extract -> detect_missing -> (ask_next_question -> END | await_approval -> export -> END)

`await_approval` calls `langgraph.types.interrupt(payload)`; the run stops and the checkpointer
stores the thread. `POST /sessions/{id}/approve` resumes with
`Command(resume={"approved": True, "record": edits, "export_target": ...})`. If `approved` is
false the node clears `export_target` and `export` becomes a no-op. The REST `export`
endpoint also refuses (`409`) unless the session status is `approved` or `exported`
(`IntakeService.export`). Every approval writes an `IntakeRecord` row with `approved_by` and an
`audit_events` row.

### Consequences

- Good: there is no code path from transcript to FHIR or Clio that does not pass a human.
  Reviewers can edit any field; evidence tooltips make the check quick.
- Good: LangGraph's interrupt/resume is the idiomatic way to model this and it demonstrates
  the pattern cleanly for the teaching docs.
- Bad: throughput is bounded by reviewers. That is intended for intake; it would be wrong for
  a high-volume classification task.
- Bad: `MemorySaver` is in-process, so an interrupted thread does not survive a restart. The
  service re-runs `finish` to rebuild the interrupt from database state before resuming
  (`IntakeService.approve`). A Postgres checkpointer is the production follow-up.
- Neutral: approving with missing required fields is allowed; the UI warns and the exporter
  omits empty values. Clinics asked for "approve anyway" more than for hard blocks.

## Confirmation

`tests/test_graph.py::test_finish_interrupts_for_approval_and_resume_exports` and
`test_rejection_does_not_export`; `tests/test_api.py` checks the `409` on early export.
