# IntakeAgent wire protocol

Two surfaces: a REST API for session lifecycle and review, and one WebSocket per live intake
session for audio in and transcript/questions out. Both are served by `backend/intakeagent/api/`.

## REST

Base URL: the backend origin (`http://127.0.0.1:8000` locally). All bodies are JSON. Errors use
FastAPI's `{"detail": "..."}` shape. Status codes: `404` unknown session, `409` invalid state
transition (for example audio after finish, export before approval), `422` validation.

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| `GET` | `/health` | | provider summary: `demo_mode`, `llm`, `stt`, `clio_mode` |
| `POST` | `/sessions` | `{"vertical": "healthcare" \| "legal"}` | session object (`201`) |
| `GET` | `/sessions` | | recent sessions |
| `GET` | `/sessions/{id}` | | session object |
| `POST` | `/sessions/{id}/text` | `{"text": "..."}` | `{record, missing_fields, next_question, next_field}` (typed fallback) |
| `POST` | `/sessions/{id}/finish` | | `{status, missing_fields, interrupt}` |
| `POST` | `/sessions/{id}/approve` | `{"record"?: {...}, "export_target"?: "fhir" \| "clio", "approved_by"?: "..."}` | `{status, record}` |
| `POST` | `/sessions/{id}/export?target=fhir\|clio` | | exporter result |
| `GET` | `/sessions/{id}/audit` | | audit events |
| `GET` | `/records` | | approved records, newest first |
| `GET` | `/schemas/{vertical}` | | field specs and JSON Schema |

### Session object

```json
{
  "id": "6f1c...", "vertical": "healthcare", "status": "recording",
  "created_at": "...", "updated_at": "...",
  "transcript": "Hi, my name is ...",
  "transcript_segments": [{"id": "a1b2", "text": "...", "start_ms": 0, "end_ms": 4000}],
  "record": {"full_name": {"value": "Sarah Mitchell", "evidence": [{"quote": "my name is Sarah Mitchell", "start": 4, "end": 29}], "confidence": 0.8}, "...": {}},
  "missing_fields": ["phone"],
  "next_question": "What is the best phone number to reach you?",
  "next_field": "phone",
  "field_specs": [{"name": "full_name", "required": true, "question": "...", "group": "demographics", "kind": "scalar"}]
}
```

`status` moves `recording -> awaiting_approval -> approved -> exported`. Approve with
`export_target` set jumps straight to `exported`.

### Record shape

Every field is `{"value": T | null, "evidence": [Evidence], "confidence": 0..1}` where
`Evidence` is `{"quote", "start", "end", "segment_id"}` and `start`/`end` are character offsets
into `transcript` (segments joined by a single space). The review UI uses them to highlight the
source. Lists (`medications`, `allergies`, `key_dates`, `conditions`, `conflict_check_names`)
carry arrays in `value`.

## WebSocket: `/ws/intake/{session_id}`

One connection per session. Text frames carry JSON; binary frames carry audio. Frames are
ordered, so a JSON `audio_meta` immediately followed by a binary frame is treated as a pair.

Connection is refused with close code `4404` when the session does not exist.

### Client to server

| `type` | Fields | Meaning |
| --- | --- | --- |
| `audio_meta` | `mime`, `seq` | Describes the next binary frame. Default `audio/webm;codecs=opus`. |
| *(binary)* | | One complete audio file (WebM/Opus or Ogg/Opus). Max 8 MB. |
| `text` | `text` | Typed utterance; takes the same path as transcribed audio. |
| `finish` | | Stop collecting; run to the approval interrupt. |
| `ping` | | Keepalive; server answers `pong`. |

### Server to client

| `type` | Fields | When |
| --- | --- | --- |
| `ready` | `session_id`, `vertical`, `status`, `stt`, `question`, `record`, `missing_fields` | Right after accept. `question` is the opener or the last question asked. |
| `status` | `state`: `listening`, `transcribing`, `thinking`, `finishing`, `awaiting_approval` | Progress for the UI pill. |
| `transcript` | `segment` | One final segment with session-relative `start_ms`/`end_ms`. |
| `extraction` | `record`, `missing_fields` | Updated structured record after each turn. |
| `question` | `text`, `field` | The agent's next question and the field it targets (null when done). |
| `awaiting_approval` | `session_id`, `record`, `missing_fields`, `review_url` | After `finish`. Client navigates to the review screen. |
| `error` | `code`, `message` | `too_large`, `stt_failed`, `invalid_state`, `bad_json`, `unknown_type`. The connection stays open. |
| `pong` | | Reply to `ping`. |

### Why complete files, not a continuous stream

`MediaRecorder` with a `timeslice` emits one WebM header followed by headerless fragments.
Whisper-style batch models need a decodable container, so the client restarts the recorder
every ~5 seconds and sends each stop's blob as a standalone file (`frontend/lib/recorder.ts`).
Latency cost is one segment length; the gain is that every STT provider, including hosted
ones, can transcribe each frame independently and failures are isolated to one segment. See
`docs/adr/ADR-0005-segmented-media-recorder.md` and ADR-0001 for the WebRTC path later.

### Timeline

Each provider returns offsets relative to its own file. `IntakeService.add_segments` shifts
them by the last known `end_ms` of the session, so the transcript timeline is monotonic even
though segments arrive as independent files.

## Example session with `websocat`

```bash
SID=$(curl -s -X POST http://127.0.0.1:8000/sessions -H 'content-type: application/json' \
  -d '{"vertical":"legal"}' | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
websocat ws://127.0.0.1:8000/ws/intake/$SID
{"type":"text","text":"My name is Daniel Okafor, phone 212-555-0188."}
{"type":"finish"}
```
