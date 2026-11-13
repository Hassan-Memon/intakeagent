# 05. Run it yourself

Exercises in three groups. Each one names the files to touch and what you should observe.
Keep `DEMO_MODE=1` unless an exercise says otherwise so nothing leaves your machine.

## Observe it

**1. Watch a session on the wire.** Start the backend
(`uv run uvicorn intakeagent.main:app --host 127.0.0.1 --port 8000`), create a session with
`curl -X POST http://127.0.0.1:8000/sessions -H 'content-type: application/json' -d
'{"vertical":"legal"}'`, then connect with `websocat ws://127.0.0.1:8000/ws/intake/<id>`. Send
`{"type":"text","text":"My name is Daniel Okafor."}` and read every frame that comes back.
Compare with `docs/protocol.md`.

**2. Read the audit trail.** After approving a record in the UI, call
`GET /sessions/<id>/audit`. Map each event to the method in `api/service.py` that wrote it.

**3. Inspect a FHIR Bundle.** Export a healthcare session and paste the `payload` into
`https://validator.fhir.org` (synthetic data only). Note which warnings are about missing
codings versus structure.

**4. See the interrupt.** In `tests/test_graph.py::test_finish_interrupts_for_approval_and_resume_exports`
add `print(graph.get_state(cfg))` before and after the resume and run with `-s`. Find the
pending task and the `__interrupt__` payload.

**4a. See the reference checks.** In the demo (or `docker compose up`), play the sample
patient and press "Finish and review". The panel flags amoxicillin against the penicillin
allergy, ticks the confident RxNorm matches and offers R10.31 for "sharp pain in my lower right
side". Tick it, acknowledge the flag, approve, export, and find the `coding` arrays in the
Bundle. Play the sample client instead: the screening table shows "Northwind Logistics" as a
possible match to the fictional "NORTHWIND LOGISTIX". Then call `POST /sessions/<id>/verify`
with an edited record (amoxicillin removed) and watch the flag disappear.

**4b. Run the tests.** `cd backend && uv run pytest` runs 69 offline tests;
`tests/test_verify.py` covers coding, allergy rules, ICD ranking, sanctions parsing and
matching, and the NLM client against a mock transport.

**4c. Use real data.** Set `DEMO_MODE=0`. `TERMINOLOGY_PROVIDER=auto` (or `nlm`) calls NLM
live with the snapshot as fallback; `offline` forces the snapshot. Download sanctions lists
with `uv run python -m intakeagent.verify.sanctions refresh --out data/sanctions.json` and set
`SANCTIONS_LIST_PATH` to that file; without it, screening reports "unavailable". Try
`uv run python -m intakeagent.verify.sanctions screen "Banco Nacional de Cuba" --list
data/sanctions.json`. Regenerate the terminology snapshot (backend and frontend copies) with
`uv run python -m intakeagent.verify.terminology snapshot`.

## Break it

**5. Kill the backend mid-intake.** Start a session in the UI, send two typed lines, stop the
backend, restart it, send another line. The transcript continues because
`IntakeService._run_graph` rehydrates from Postgres/SQLite. Now press Finish and approve: it
works because `approve` rebuilds the interrupt. Then comment out the `_thread_is_cold` branch
and repeat to see what breaks.

**6. Send garbage audio.** With `STT_PROVIDER=groq` and a key (synthetic speech only), send a
text file as a binary frame. Observe `error: stt_failed` and that the session stays open.

**7. Approve twice.** Call `POST /sessions/<id>/approve` twice in a row. The second returns 409.
Remove the status check in `IntakeService.approve` and see the duplicate `intake_records` row.

**8. Exhaust the threadpool.** Add `time.sleep(10)` inside `RuleBasedExtractor.extract`, open
50 WebSocket connections with a script and send one text frame each. Watch REST calls stall.
Then move graph execution to a dedicated `ThreadPoolExecutor` and compare.

**8a. Starve the verifier.** With `DEMO_MODE=0`, point `SANCTIONS_LIST_PATH` at a missing file
and finish a legal intake: the panel must say screening did not run, not "clear". Then block
`rxnav.nlm.nih.gov` (hosts file) and finish a healthcare intake: the sources line should read
"bundled snapshot".

**9. Make redaction miss.** Add a transcript line with a name that has no introduction phrase
("Spoke with Tariq earlier."). Run `redact()` on it. Write a new pattern or wire up Presidio
via the `presidio` extra and add a test in `tests/test_redaction.py`.

## Extend it

**10. Silence-based segmentation.** In `frontend/lib/recorder.ts`, end a segment when the RMS
level stays below 0.02 for 400 ms instead of on a fixed timer (keep a 10-second maximum).
Compare transcript quality on real speech.

**11. Reconnect with backoff.** In `frontend/lib/ws.ts`, reopen the socket after `onClose` with
exponential backoff and resume from the session's persisted state. Show a "reconnecting" pill.

**12. Postgres checkpointer.** Add `langgraph-checkpoint-postgres`, create a `PostgresSaver`
from `DATABASE_URL` when it is Postgres, and pass it to `build_intake_graph`. Verify exercise 5
now works without the rehydration branch.

**13. Idempotent FHIR.** Add `"ifNoneExist": "Patient?identifier=urn:intakeagent:session|{sid}"`
to the Patient entry's `request` in `exporters/fhir.py` and prove with a mock transport test
that the body contains it.

**14. Whisper prompting.** Pass an `initial_prompt` with the vertical's vocabulary to
faster-whisper and a `prompt` form field to Groq. Measure the effect on drug names.

**15. A third vertical.** Create `schemas/dental.py` with `intake_field` metadata, register it
in `schemas/__init__.py`, add seed protocol snippets, and extend the frontend's `vertLabel`.
Everything else should just work; note anything that did not.

**16. Real LLM extraction.** Install Ollama, pull `llama3.2`, set `DEMO_MODE=0` and
`LLM_PROVIDER=ollama`. Compare the LLM's record against the rules on the demo script. Then set
`LLM_PROVIDER=groq` with `ALLOW_CLOUD_LLM=0` and confirm it refuses and falls back; flip the
flag and inspect the redacted prompt by adding a log line in `LLMExtractor.extract`.

**17. Streaming partials.** Design (do not build) the WebRTC path from ADR-0001: which
component changes, which stays, and what the new `transcript` frame with `final: false` would
look like.
