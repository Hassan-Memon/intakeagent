# 01. Architecture walkthrough

IntakeAgent has four boxes: a Next.js frontend, a FastAPI backend that hosts a LangGraph
graph, a Postgres database with pgvector, and two external targets (a FHIR server and Clio).
This lesson follows one healthcare intake from the first click to the exported Bundle and
explains why each box exists.

## Why the boxes exist

**Frontend (`frontend/`).** The browser is the only place that can access the microphone, so
capture has to happen there. Next.js gives us routing (`/`, `/intake/[id]`, `/review/[id]`,
`/records`), a build step that type-checks everything, and free hosting on Vercel. The pages
are thin: they fetch JSON, render forms, and open a WebSocket.

**Backend (`backend/intakeagent/`).** Everything with a secret, a model or a database
connection lives here. FastAPI serves REST (`api/rest.py`) and the WebSocket (`api/ws.py`).
Both delegate to one class, `IntakeService` (`api/service.py`), which is the only code that
talks to the graph and the database. That single choke point is what makes the "no export
without approval" guarantee enforceable.

**LangGraph graph (`graph/builder.py`).** A plain function could extract fields from text.
A graph earns its place because the conversation is stateful and pausable: it accumulates
transcript across turns, decides what to ask next, and must stop and wait for a human. The
checkpointer keyed by session id gives us that for free.

**Database (`db/`).** Sessions and approved records are relational data with an audit trail.
Protocol snippets for grounding questions are vectors. Postgres with pgvector covers both;
SQLite covers tests.

**Exporters (`exporters/`).** FHIR and Clio are the systems the clinic and firm already own.
Producing their native formats is the difference between a demo and a tool.

## The request path, end to end

1. **Choose a vertical.** `components/StartIntake.tsx` calls `POST /sessions` with
   `{"vertical": "healthcare"}`. `IntakeService.create_session` inserts an `IntakeSession` row
   with status `recording` and the opening question from `graph/questions.py`, and writes an
   `audit_events` row. The browser navigates to `/intake/{id}`.

2. **Connect.** `components/IntakeClient.tsx` fetches the session (for field specs), then
   `lib/ws.ts` opens `ws://.../ws/intake/{id}`. The server replies `ready` with the question.

3. **Capture.** On "Start microphone", `lib/recorder.ts` requests the mic, starts a
   `MediaRecorder`, and every five seconds stops it and starts another, so each blob is a
   complete WebM/Opus file. Each blob is sent as `audio_meta` JSON followed by a binary frame.
   An `AnalyserNode` drives the level meter.

4. **Transcribe.** `api/ws.py` hands the bytes to the STT provider chosen in `stt/base.py`:
   stub (scripted lines), Groq Whisper, or faster-whisper. It gets back timed segments.

5. **Run one graph turn.** `IntakeService.add_segments` shifts the segment times onto the
   session timeline and invokes the graph with `{"transcript_segments": [...], "finished":
   False}` and `thread_id = session id`. Nodes run in order: `merge_transcript` joins segments
   and records char offsets; `extract` calls the extractor (`graph/extractors.py`), which in
   demo mode is regex rules and otherwise an LLM behind `llm/provider.py`, with redaction if
   the provider is not local; `detect_missing` compares the record against the schema's
   `required_for_intake` metadata (`schemas/base.py`); `ask_next_question` picks the first
   missing field's question and appends a protocol hint from the RAG store.

6. **Stream back.** The handler sends `transcript`, `extraction` and `question` frames. The
   UI appends the segment, updates the checklist, and reads the question aloud via
   `aria-live`.

7. **Finish.** The user clicks "Finish and review"; the client sends `{"type": "finish"}`.
   `IntakeService.finish` invokes the graph with `finished=True`. Routing now goes to
   `await_approval`, which calls `interrupt()`; the graph stops. Status becomes
   `awaiting_approval` and the client navigates to `/review/{id}`.

8. **Review.** `components/ReviewClient.tsx` renders `RecordForm` from the field specs.
   Hovering the "i" shows the evidence quote and highlights the span in the transcript.
   The reviewer edits and clicks Approve: `POST /sessions/{id}/approve` with the edited record.
   `IntakeService.approve` resumes the graph with `Command(resume=...)`, the `await_approval`
   node validates the edits, `export` runs if a target was requested, and an `IntakeRecord`
   row is written.

9. **Export.** `POST /sessions/{id}/export?target=fhir` calls `exporters/fhir.py`, which builds
   a transaction Bundle with `fhir.resources`, pushes it only if `FHIR_PUSH=1`, and stores the
   result on the record. `/records` lists everything approved.

## What to notice

Audio never touches disk. The graph is re-invoked per utterance, which keeps each turn short
and restart-safe. The only path into `export` goes through `interrupt()`. Every provider has a
stub, which is why `DEMO_MODE=1` runs with no keys and the tests finish in seconds.
