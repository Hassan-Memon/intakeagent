"""SQLModel tables.

SQLModel is SQLAlchemy plus Pydantic: one class is both the ORM table and a validated model.
JSON columns keep the schema flexible while the Pydantic intake models remain the source of
truth for what a record looks like. Works on SQLite (tests, laptop) and Postgres (compose,
Neon) without changes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return uuid.uuid4().hex


class IntakeSession(SQLModel, table=True):
    __tablename__ = "intake_sessions"

    id: str = Field(default_factory=_uuid, primary_key=True)
    vertical: str = Field(index=True)
    # recording -> awaiting_approval -> approved -> exported
    status: str = Field(default="recording", index=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    transcript_segments: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    transcript: str = Field(default="", sa_column=Column(Text))
    record: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    missing_fields: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    questions_asked: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    next_question: str | None = Field(default=None, sa_column=Column(Text))
    next_field: str | None = None


class IntakeRecord(SQLModel, table=True):
    """An approved record. Created when a human approves; updated on export."""

    __tablename__ = "intake_records"

    id: str = Field(default_factory=_uuid, primary_key=True)
    session_id: str = Field(index=True, foreign_key="intake_sessions.id")
    vertical: str = Field(index=True)
    record: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    approved_at: datetime = Field(default_factory=_now)
    approved_by: str = Field(default="front-desk")
    export_target: str | None = None
    export_result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    exported_at: datetime | None = None


class AuditEvent(SQLModel, table=True):
    """Append-only trail of who did what to which session (HIPAA 164.312(b))."""

    __tablename__ = "audit_events"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=_now, index=True)
    session_id: str = Field(index=True)
    actor: str = Field(default="system")
    action: str
    detail: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class ProtocolDoc(SQLModel, table=True):
    """Intake protocol snippets used for RAG hints. Embedding stored as JSON for portability;
    Postgres deployments additionally get a pgvector column (see db/rag.py)."""

    __tablename__ = "protocol_docs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    vertical: str = Field(index=True)
    field_name: str = Field(index=True)
    title: str
    content: str = Field(sa_column=Column(Text))
    embedding: list[float] = Field(default_factory=list, sa_column=Column(JSON))
