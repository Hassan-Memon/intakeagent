# 02. System design trade-offs

This lesson looks at IntakeAgent the way an interviewer would: what scales, what fails, and
what you would change first.

## Where the load is

One session produces a 5-second audio segment every 5 seconds (80 to 120 KB of Opus), one STT
call and one graph turn per segment, and a few small JSON frames back. A clinic with four
front-desk stations runs four concurrent sessions; a regional group might run 200. The
expensive steps are STT (0.5 to 3 s on CPU or a vendor call) and LLM extraction (1 to 5 s
locally).

## Back-pressure

The WebSocket handler in `api/ws.py` processes frames sequentially per connection: await STT,
await the graph turn in a worker thread, read the next frame. If the client sends segments
faster than the server finishes them, frames queue in the socket buffer. Fine for one slow
turn; unbounded under sustained overload.

Fixes, in order of effort: cap the per-connection queue and merge old segments; move STT and
extraction to a worker pool (arq, Celery or a RabbitMQ consumer) so the socket handler only
enqueues; send a `status` frame telling the client to pause recording. The protocol already
has `status` for this.

## Failure modes

| Failure | Today | Production answer |
| --- | --- | --- |
| STT provider down | `error: stt_failed`, session continues, one segment lost | Retry with backoff, fall through to the next provider, buffer audio |
| LLM timeout or bad JSON | `LLMExtractor` falls back to rules | Same, plus circuit breaker and a "degraded" flag on the record |
| Backend restart mid-session | Transcript and record survive in Postgres; `MemorySaver` thread is lost; `_run_graph` rehydrates from the DB | `langgraph-checkpoint-postgres` so interrupts survive |
| Postgres unreachable | 500s | Connection retry, fast-failing health check |
| FHIR server rejects the Bundle | Response stored, status still `exported` | Treat non-2xx as failed, keep `approved`, show the OperationOutcome |
| Clio token expired | Export errors | Call `ClioOAuthClient.refresh` on 401 and persist the token |

## Idempotency

Repeating `POST /sessions/{id}/export` in live mode creates a second Clio Contact and Matter,
and FHIR `POST` entries create duplicates too. The fix is conditional create: FHIR's
`ifNoneExist` on the Patient entry (`Patient?identifier=urn:intakeagent:session|{id}`) and a
Clio contact search by email before creating. Approval is idempotent already: a second approve
returns `409`.

## Consistency

`IntakeService` writes the session row, the approved record and the audit event in one
SQLModel session and commits once. There is no shared transaction with the graph checkpointer;
the database is the source of truth and the checkpointer is a rebuildable cache.

## What breaks first at 10x

1. **Single-process STT.** faster-whisper on CPU keeps up with one stream. At ten, the socket
   queue grows. Move STT out of process first (GPU worker or a hosted provider with a BAA).
2. **Threadpool exhaustion.** `asyncio.to_thread` shares the default executor (about 40
   threads). Long LLM calls starve REST requests. Give the graph its own executor or a queue.
3. **Memory checkpointer.** Every session's state stays in RAM until the process dies. Use the
   Postgres checkpointer and delete threads after export.
4. **Postgres connections.** Neon's free tier caps them. Use the pooled endpoint or PgBouncer.
5. **Review throughput.** Ten times the intakes is ten times the reviewer minutes. The answer
   is better evidence display and confidence sorting, not removing the human.

## Scaling the WebSocket tier

WebSockets are sticky, but nothing else is: state lives in Postgres and the graph rehydrates.
Any load balancer that supports upgrade can spread sessions across replicas. Render's free
tier is one instance; Fly or Kubernetes add replicas with a shared database.

## Security boundaries

The frontend holds no secrets. The backend trusts no input: Pydantic validates bodies, the
WebSocket caps frames at 8 MB, `CORS_ORIGINS` restricts browsers. Authentication is left to
an identity layer in front (see `docs/compliance.md`).

## Cost model

On free tiers a session costs nothing until Render's sleep timer, Neon's storage cap or Groq's
rate limit. The first paid line item in a real deployment is STT compute, then the database.
