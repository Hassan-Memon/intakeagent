"""Intake-protocol RAG.

The agent's follow-up questions are grounded in short protocol snippets ("when asking about
medications, also confirm dose and frequency"). Snippets are embedded and stored; at question
time we retrieve the best match for the missing field and append it as a hint.

Two stores behind one protocol:

* ``PgVectorStore``: Postgres with the pgvector extension. Embeddings live in a dedicated
  ``protocol_embeddings`` table with a ``vector`` column and cosine distance (``<=>``).
* ``InMemoryStore``: pure Python cosine similarity over the JSON embeddings in ``protocol_docs``.
  Used with SQLite and in tests.

Embeddings likewise have two implementations: an OpenAI-compatible HTTP embedder (OpenInfer,
Ollama) and a deterministic hashing embedder for offline use.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx
from sqlalchemy import Engine, text
from sqlmodel import Session, select

from intakeagent.db.models import ProtocolDoc

EMBED_DIM = 256


class Embeddings(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbeddings:
    """Deterministic bag-of-words hashing embedder (no model, no network).

    Each token is hashed into one of EMBED_DIM buckets, the vector is L2 normalised. It is not
    semantic, but it ranks snippets that share vocabulary with the query, which is all the
    protocol hints need in DEMO_MODE.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * EMBED_DIM
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)  # noqa: S324 (not security)
                vec[h % EMBED_DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class OpenAICompatibleEmbeddings:
    """POST /v1/embeddings on any OpenAI-compatible server (OpenInfer, Ollama, Groq)."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._key = api_key
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            self._url,
            json={"model": self._model, "input": texts},
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class ProtocolStore(Protocol):
    def add(self, docs: list[ProtocolDoc]) -> None: ...
    def search(self, query: str, vertical: str, k: int = 3) -> list[tuple[ProtocolDoc, float]]: ...
    def count(self, vertical: str | None = None) -> int: ...


class InMemoryStore:
    def __init__(self, engine: Engine, embeddings: Embeddings) -> None:
        self._engine = engine
        self._emb = embeddings

    def add(self, docs: list[ProtocolDoc]) -> None:
        vectors = self._emb.embed([d.content for d in docs])
        with Session(self._engine) as s:
            for d, v in zip(docs, vectors, strict=True):
                d.embedding = v
                s.add(d)
            s.commit()

    def search(self, query: str, vertical: str, k: int = 3) -> list[tuple[ProtocolDoc, float]]:
        q = self._emb.embed([query])[0]
        with Session(self._engine) as s:
            docs = s.exec(select(ProtocolDoc).where(ProtocolDoc.vertical == vertical)).all()
        scored = [(d, cosine(q, d.embedding)) for d in docs]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def count(self, vertical: str | None = None) -> int:
        with Session(self._engine) as s:
            stmt = select(ProtocolDoc)
            if vertical:
                stmt = stmt.where(ProtocolDoc.vertical == vertical)
            return len(s.exec(stmt).all())


class PgVectorStore(InMemoryStore):
    """pgvector-backed search. Falls back to the parent class for everything but search."""

    def __init__(self, engine: Engine, embeddings: Embeddings, dim: int = EMBED_DIM) -> None:
        super().__init__(engine, embeddings)
        self._dim = dim
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS protocol_embeddings (
                        doc_id TEXT PRIMARY KEY REFERENCES protocol_docs(id) ON DELETE CASCADE,
                        vertical TEXT NOT NULL,
                        embedding vector({dim}) NOT NULL
                    )
                    """
                )
            )
            # HNSW index for approximate nearest neighbour search with cosine distance.
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS protocol_embeddings_hnsw "
                    "ON protocol_embeddings USING hnsw (embedding vector_cosine_ops)"
                )
            )

    def add(self, docs: list[ProtocolDoc]) -> None:
        super().add(docs)
        with self._engine.begin() as conn:
            for d in docs:
                conn.execute(
                    text(
                        "INSERT INTO protocol_embeddings (doc_id, vertical, embedding) "
                        "VALUES (:id, :vertical, :emb) ON CONFLICT (doc_id) DO UPDATE "
                        "SET embedding = EXCLUDED.embedding"
                    ),
                    {"id": d.id, "vertical": d.vertical, "emb": str(d.embedding)},
                )

    def search(self, query: str, vertical: str, k: int = 3) -> list[tuple[ProtocolDoc, float]]:
        q = self._emb.embed([query])[0]
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT doc_id, 1 - (embedding <=> CAST(:q AS vector)) AS score "
                    "FROM protocol_embeddings WHERE vertical = :vertical "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
                ),
                {"q": str(q), "vertical": vertical, "k": k},
            ).all()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        scores = {r[0]: float(r[1]) for r in rows}
        with Session(self._engine) as s:
            docs = s.exec(select(ProtocolDoc).where(ProtocolDoc.id.in_(ids))).all()  # type: ignore[attr-defined]
        by_id = {d.id: d for d in docs}
        return [(by_id[i], scores[i]) for i in ids if i in by_id]


def build_store(engine: Engine, embeddings: Embeddings) -> ProtocolStore:
    if str(engine.url).startswith("postgres"):
        return PgVectorStore(engine, embeddings)
    return InMemoryStore(engine, embeddings)
