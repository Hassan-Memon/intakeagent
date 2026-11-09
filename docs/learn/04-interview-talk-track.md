# 04. Interview talk track

## The two-minute version

"IntakeAgent is a voice-first intake agent for clinics and law firms. A patient or client talks
into a browser; audio streams over a WebSocket to a FastAPI backend in five-second segments;
Whisper transcribes each one; a LangGraph graph extracts a typed record, works out which
required fields are still missing, and asks the next question. When the person is done, the
graph pauses on a LangGraph interrupt. A staff member reviews the record with evidence
tooltips showing the exact sentence each value came from, edits it, and approves. Only then
does it export: a FHIR R4 transaction Bundle for healthcare, or a Clio Contact and Matter via
their v4 API with a conflict check for legal.

Two design commitments: human approval enforced in the graph topology, and local-first PHI
handling. The LLM runs on Ollama or an OpenInfer box tagged private by default; any opt-in
cloud call sees a redacted transcript that is re-hydrated locally. It runs with zero API keys
in demo mode, has forty offline tests, and deploys free on Vercel, Render and Neon."

## The fifteen-minute version

Walk the README sequence diagram, then go one layer deeper on each:

1. **Transport (3 min).** WebSocket not WebRTC for an MVP (ADR-0001); complete files not a
   byte stream (ADR-0005); the `audio_meta` + binary pair; error frames keep the socket alive.
2. **Graph (4 min).** Reducers with `operator.add`; six nodes; conditional edge on `finished`;
   `interrupt()` and `Command(resume=...)`; checkpointer per session; rehydration from Postgres.
   `with_structured_output(PatientIntake)`, evidence quotes resolved to spans, merge with the
   previous record, fallback to rules on failure.
3. **Schemas (2 min).** `Extracted[T]` with value, evidence, confidence. Metadata in
   `json_schema_extra` drives the missing-field detector, question picker and review layout.
4. **Privacy (3 min).** Provider resolution order; `is_local`; `ALLOW_CLOUD_LLM`; typed
   placeholders; what regex does not guarantee; the HIPAA table and "does not yet" list.
5. **Exports (2 min).** fhir.resources validation; transaction Bundle with `urn:uuid`
   references; Clio OAuth2 code flow and `{"data": ...}` envelopes; mock-transport tests.
6. **Operations (1 min).** What breaks first at 10x and the idempotency gap on export retries.

## Numbers to quote

- 6 graph nodes, 2 verticals, 14 and 12 schema fields, 7 FHIR resource types.
- 40 offline tests in about 10 to 15 seconds.
- 5-second segments, 80 to 120 KB each as Opus; 8 MB frame cap.
- faster-whisper `base` on CPU roughly real time; Groq whisper-large-v3 usually under 1 s.
- 5 frontend routes, 104 to 111 KB first-load JS.
- Zero required API keys; three optional free ones.

## Ten likely questions

**1. Why not auto-export when confidence is high?** Liability sits with the clinic or firm.
The approval node is the only edge into export, so the guarantee is structural. Confidence
can sort the review queue, not bypass it.

**2. A WebSocket drops mid-intake. Then what?** Transcript and record persist per turn, so a
reconnect continues the session; the graph thread rebuilds from the database. One in-flight
segment is lost, which is five seconds.

**3. Is regex redaction enough?** It is the second line of defence; the first is not sending
PHI out at all. For real PHI keep the LLM local, add Presidio as a layer, and never claim
de-identification.

**4. Two reviewers approve at once?** The second gets a 409 from the status check. Harden with
a unique constraint on `intake_records.session_id` and optimistic locking.

**5. How do you add a third vertical?** A Pydantic schema with `intake_field` metadata, a
registry entry, seed protocol snippets, and an exporter if the target differs. Graph, service,
API and review UI are schema-driven.

**6. Why pgvector, not Qdrant?** Tiny corpus, and transactional consistency matters more than
ANN speed. HNSW scales to millions; the store sits behind a protocol for later swaps (ADR-0006).

**7. How do segment timestamps stay consistent?** Each provider returns file-relative offsets;
the service adds the session's last `end_ms`. Evidence spans are char offsets into the merged
transcript, recomputed identically on the client.

**8. Where does the latency go?** About 5 s buffering, 0.5 to 3 s STT, 0.1 s rules or 1 to 5 s
local LLM. Fine for intake. A spoken agent would need WebRTC with streaming STT.

**9. FHIR references before ids exist?** Transaction Bundles use `urn:uuid` full URLs the server
rewrites atomically. For idempotent retries, add `ifNoneExist` on the Patient entry.

**10. First week with funding?** Postgres checkpointer, OIDC in front of REST and WebSocket,
silence-based segmentation, and a retention and erasure endpoint. Those close the biggest gaps
in `docs/compliance.md`.
