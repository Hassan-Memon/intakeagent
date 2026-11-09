# SQLModel and pgvector

## SQLModel: one class, two jobs

SQLModel (by the FastAPI author) layers Pydantic on SQLAlchemy. A class with `table=True` is
both a database table and a validated model:

    class IntakeRecord(SQLModel, table=True):
        id: str = Field(default_factory=_uuid, primary_key=True)
        record: dict = Field(sa_column=Column(JSON))

`backend/intakeagent/db/models.py` defines four tables: `intake_sessions` (live state),
`intake_records` (approved snapshots), `audit_events` (append-only log) and `protocol_docs`
(RAG snippets). JSON columns hold the flexible parts (transcript segments, the record) while
the Pydantic intake schemas remain the typed contract; the database does not need to know every
field, and schema changes do not need migrations for new fields.

## Sessions and transactions

`with Session(engine) as s:` opens a unit of work. `s.add(row)`, `s.commit()`, `s.refresh(row)`
is the rhythm. `IntakeService` writes the session row, the approved record and the audit event
in one `Session` and commits once, so they succeed or fail together. `select(Model).where(...)`
builds typed queries; `s.exec(stmt).all()` runs them.

## SQLite for tests, Postgres for real

`create_db_engine` in `db/engine.py` builds a SQLAlchemy engine from `DATABASE_URL`. SQLite
needs `check_same_thread=False` because FastAPI may touch a connection from a worker thread.
Postgres gets `pool_pre_ping=True` so stale connections are detected. `init_db` creates the
`vector` extension on Postgres and then `SQLModel.metadata.create_all(engine)` creates
tables. Alembic migrations are the production follow-up; for an MVP `create_all` is enough.

## pgvector: vectors as a column type

pgvector adds a `vector(n)` column type and distance operators to Postgres: `<->` (L2),
`<=>` (cosine distance), `<#>` (negative inner product). An embedding is just a column, so you
can join it with everything else and keep it in the same transaction.

`db/rag.py` creates a `protocol_embeddings` table with `embedding vector(256)` and an index:

    CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)

HNSW (Hierarchical Navigable Small World) is an approximate nearest-neighbour graph index.
Without it, Postgres scans every row (fine for hundreds, slow for millions). With it, queries
are logarithmic at the cost of slightly approximate results and slower inserts. The alternative
`ivfflat` index is cheaper to build and needs training data; HNSW is the default choice today.

Searching is a normal query ordered by distance:

    SELECT doc_id, 1 - (embedding <=> CAST(:q AS vector)) AS score
    FROM protocol_embeddings WHERE vertical = :v
    ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k

The vector literal is a string like `[0.1, 0.2, ...]`, which is why the code passes
`str(list_of_floats)`.

## Embeddings

Two implementations behind one protocol. `OpenAICompatibleEmbeddings` posts to
`/v1/embeddings` on OpenInfer or Ollama (`nomic-embed-text` is a good local model).
`HashingEmbeddings` hashes tokens into 256 buckets and normalises; it is lexical, not semantic,
but deterministic and offline, which is what tests and the demo need. The dimension must match
the column (`vector(256)`); switching to a real model with 768 dimensions means a new column.

## In-memory fallback

`InMemoryStore` loads the JSON embeddings from `protocol_docs` and computes cosine similarity
in Python. It is the SQLite path, and it is also the reason the whole RAG layer is testable in
`tests/test_rag.py` without Postgres. `build_store` picks `PgVectorStore` or `InMemoryStore`
by inspecting the URL. Callers see only `ProtocolStore`.

## How RAG is used here

It is deliberately small: the `ask_next_question` node asks the store for the best protocol
snippet for the missing field and appends it as a hint. That grounds the question in the
clinic's own protocol without a prompt rewrite. Replacing the seed snippets in
`db/seed_protocols.py` with a customer's intake manual is the first real customisation.
