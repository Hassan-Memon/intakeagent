# ADR-0006: SQLModel on Postgres with pgvector before a dedicated vector DB

- Status: accepted
- Date: 2026-11-09
- Deciders: Hassan Memon

## Context and problem statement

The service needs relational persistence (sessions, approved records, audit events) and a
small semantic store for intake-protocol snippets that ground the agent's questions. Should
the vector store be a separate product (Qdrant, Pinecone, Weaviate) or live in Postgres?

## Decision drivers

- Free tiers: Neon gives Postgres with `pgvector`; Qdrant Cloud gives 1 GB. Both are free,
  but one database is simpler to operate and back up than two.
- The corpus is tiny (tens to low thousands of protocol snippets per tenant).
- Tests must run offline on SQLite with no services.
- Transactional consistency between a record and its audit event matters more than ANN speed.

## Considered options

1. Postgres + pgvector for everything; SQLite fallback with in-Python cosine for tests.
2. Postgres for relational data, Qdrant for vectors.
3. SQLite + a local FAISS index.

## Decision outcome

Chosen option 1. `backend/intakeagent/db/models.py` defines `IntakeSession`, `IntakeRecord`,
`AuditEvent` and `ProtocolDoc` with SQLModel (SQLAlchemy + Pydantic in one class). JSON
columns hold the flexible record while the Pydantic schemas remain the typed source of truth.
`backend/intakeagent/db/rag.py` exposes a `ProtocolStore` protocol with two implementations:
`PgVectorStore` (a `protocol_embeddings` table with a `vector(256)` column, HNSW index with
`vector_cosine_ops`, `<=>` distance) and `InMemoryStore` (cosine in Python over JSON
embeddings) chosen by the database URL. Embeddings come from an OpenAI-compatible
`/v1/embeddings` endpoint or, offline, a deterministic hashing embedder.

### Consequences

- Good: one `DATABASE_URL`, one backup, one connection pool; joins between protocol hits and
  tenant metadata are plain SQL.
- Good: the whole test suite runs on SQLite in under 20 seconds with no containers.
- Good: HNSW in pgvector handles millions of vectors; we will not outgrow it on protocol text.
- Bad: pgvector lacks some dedicated-DB features (hybrid search with BM25 built in, payload
  filtering at scale, multi-tenant collections). Postgres `tsvector` covers simple hybrid
  search when needed.
- Bad: the hashing embedder is lexical, not semantic; it is a demo stand-in, which is why the
  question picker also falls back to exact field-name matches (`seed_protocols.hint_for`).
- Trigger to revisit: per-tenant corpora above a few million chunks, or a need for
  sub-10 ms filtered ANN at high QPS. At that point add Qdrant behind the same
  `ProtocolStore` protocol; callers do not change.

## Confirmation

`tests/test_rag.py` covers the embedder, seeding idempotency, search ranking and hint lookup.
`PgVectorStore` is exercised manually against the compose Postgres (no Postgres in CI yet).
