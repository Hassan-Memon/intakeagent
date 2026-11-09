"""IntakeService: the one place that touches the graph, the database and the exporters.

REST and WebSocket handlers are thin; they call this. Methods are synchronous (SQLModel and
the compiled graph are sync) and the WebSocket handler runs them in a worker thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command
from sqlalchemy import Engine
from sqlmodel import Session, select

from intakeagent.db.models import AuditEvent, IntakeRecord, IntakeSession
from intakeagent.graph.questions import opener
from intakeagent.schemas import schema_for
from intakeagent.stt.base import TranscriptSegment

log = logging.getLogger(__name__)

ExporterFn = Callable[[str, dict[str, Any], str], dict[str, Any]]


class SessionNotFound(LookupError):
    pass


class InvalidTransition(ValueError):
    pass


@dataclass
class TurnResult:
    session_id: str
    status: str
    record: dict[str, Any]
    missing_fields: list[str]
    next_question: str | None
    next_field: str | None
    transcript: str
    interrupt: dict[str, Any] | None = None
    export_result: dict[str, Any] | None = None
    new_segments: list[dict[str, Any]] = field(default_factory=list)


class IntakeService:
    def __init__(self, engine: Engine, graph: Any, exporters: dict[str, ExporterFn]) -> None:
        self._engine = engine
        self._graph = graph
        self._exporters = exporters

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _config(session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id}}

    def _audit(self, s: Session, session_id: str, action: str, **detail: Any) -> None:
        s.add(AuditEvent(session_id=session_id, action=action, detail=detail))

    def _load(self, s: Session, session_id: str) -> IntakeSession:
        row = s.get(IntakeSession, session_id)
        if row is None:
            raise SessionNotFound(session_id)
        return row

    def _thread_is_cold(self, session_id: str) -> bool:
        """True when the checkpointer has no state for this session (fresh process)."""
        snapshot = self._graph.get_state(self._config(session_id))
        return not snapshot.values

    def _run_graph(
        self, row: IntakeSession, new_segments: list[dict[str, Any]], finished: bool
    ) -> dict[str, Any]:
        segments = new_segments
        if self._thread_is_cold(row.id):
            # Rehydrate from the database so a restarted server can continue a session.
            segments = [*row.transcript_segments, *new_segments]
        payload: dict[str, Any] = {
            "session_id": row.id,
            "vertical": row.vertical,
            "transcript_segments": segments,
            "finished": finished,
        }
        if self._thread_is_cold(row.id) and row.record:
            payload["record"] = row.record
        return self._graph.invoke(payload, self._config(row.id))

    def _apply_state(self, row: IntakeSession, state: dict[str, Any]) -> None:
        row.transcript = state.get("transcript", row.transcript)
        row.record = state.get("record", row.record)
        row.missing_fields = state.get("missing_fields", row.missing_fields)
        if state.get("next_question"):
            row.next_question = state["next_question"]
            row.next_field = state.get("next_field")
            row.questions_asked = state.get("questions_asked", row.questions_asked)
        row.updated_at = datetime.now(UTC)

    def _result(self, row: IntakeSession, state: dict[str, Any]) -> TurnResult:
        interrupts = state.get("__interrupt__") or []
        interrupt_payload = None
        if interrupts:
            first = interrupts[0]
            interrupt_payload = getattr(first, "value", first)
        return TurnResult(
            session_id=row.id,
            status=row.status,
            record=row.record,
            missing_fields=row.missing_fields,
            next_question=row.next_question,
            next_field=row.next_field,
            transcript=row.transcript,
            interrupt=interrupt_payload,
            export_result=state.get("export_result"),
        )

    # -- public API ---------------------------------------------------------------

    def create_session(self, vertical: str) -> IntakeSession:
        schema_for(vertical)  # raises KeyError for unknown vertical
        row = IntakeSession(vertical=vertical, next_question=opener(vertical))
        with Session(self._engine) as s:
            s.add(row)
            self._audit(s, row.id, "session.created", vertical=vertical)
            s.commit()
            s.refresh(row)
        return row

    def get_session(self, session_id: str) -> IntakeSession:
        with Session(self._engine) as s:
            return self._load(s, session_id)

    def list_sessions(self, limit: int = 50) -> list[IntakeSession]:
        with Session(self._engine) as s:
            stmt = select(IntakeSession).order_by(IntakeSession.created_at.desc()).limit(limit)  # type: ignore[attr-defined]
            return list(s.exec(stmt).all())

    def add_segments(self, session_id: str, segments: list[TranscriptSegment]) -> TurnResult:
        """Append transcript segments (shifted onto the session timeline) and run one turn."""
        with Session(self._engine) as s:
            row = self._load(s, session_id)
            if row.status != "recording":
                raise InvalidTransition(f"session is {row.status}; no more audio accepted")
            offset = max((seg.get("end_ms", 0) for seg in row.transcript_segments), default=0)
            shifted = [
                {
                    **seg.model_dump(),
                    "start_ms": seg.start_ms + offset,
                    "end_ms": seg.end_ms + offset,
                }
                for seg in segments
                if seg.text.strip()
            ]
            state = self._run_graph(row, shifted, finished=False)
            row.transcript_segments = [*row.transcript_segments, *shifted]
            self._apply_state(row, state)
            self._audit(s, row.id, "transcript.appended", segments=len(shifted))
            s.add(row)
            s.commit()
            s.refresh(row)
            result = self._result(row, state)
            result.new_segments = shifted
            return result

    def add_text(self, session_id: str, text: str) -> TurnResult:
        """Typed input (accessibility fallback and tests) goes through the same path."""
        seg = TranscriptSegment(id=f"t{datetime.now(UTC).timestamp():.0f}", text=text)
        return self.add_segments(session_id, [seg])

    def finish(self, session_id: str) -> TurnResult:
        """User is done talking: run to the approval interrupt."""
        with Session(self._engine) as s:
            row = self._load(s, session_id)
            if row.status not in ("recording", "awaiting_approval"):
                raise InvalidTransition(f"session is {row.status}")
            state = self._run_graph(row, [], finished=True)
            self._apply_state(row, state)
            row.status = "awaiting_approval"
            self._audit(s, row.id, "session.finished", missing=row.missing_fields)
            s.add(row)
            s.commit()
            s.refresh(row)
            return self._result(row, state)

    def approve(
        self,
        session_id: str,
        record: dict[str, Any] | None = None,
        export_target: str | None = None,
        approved_by: str = "front-desk",
    ) -> tuple[IntakeRecord, TurnResult]:
        """Resume the graph past the HITL interrupt with the reviewer's (edited) record."""
        with Session(self._engine) as s:
            row = self._load(s, session_id)
            if row.status not in ("recording", "awaiting_approval"):
                raise InvalidTransition(f"session is {row.status}")
            if export_target and export_target not in self._exporters:
                raise InvalidTransition(f"unknown export target {export_target}")

            snapshot = self._graph.get_state(self._config(row.id))
            if "await_approval" not in (snapshot.next or ()):
                # Not parked at the interrupt (fresh process or finish never called).
                self._run_graph(row, [], finished=True)

            if record:
                schema_for(row.vertical)(**record)  # validate edits before resuming
            state = self._graph.invoke(
                Command(
                    resume={"approved": True, "record": record, "export_target": export_target}
                ),
                self._config(row.id),
            )
            self._apply_state(row, state)
            row.status = "exported" if state.get("export_result") else "approved"
            approved = IntakeRecord(
                session_id=row.id,
                vertical=row.vertical,
                record=row.record,
                approved_by=approved_by,
                export_target=export_target if state.get("export_result") else None,
                export_result=state.get("export_result"),
                exported_at=datetime.now(UTC) if state.get("export_result") else None,
            )
            s.add(approved)
            self._audit(s, row.id, "record.approved", by=approved_by, edited=bool(record))
            if state.get("export_result"):
                self._audit(s, row.id, "record.exported", target=export_target)
            s.add(row)
            s.commit()
            s.refresh(row)
            s.refresh(approved)
            return approved, self._result(row, state)

    def export(self, session_id: str, target: str) -> dict[str, Any]:
        """Export an approved record (again, or for the first time) to a target."""
        if target not in self._exporters:
            raise InvalidTransition(f"unknown export target {target}")
        with Session(self._engine) as s:
            row = self._load(s, session_id)
            if row.status not in ("approved", "exported"):
                raise InvalidTransition("record must be approved before export")
            stmt = (
                select(IntakeRecord)
                .where(IntakeRecord.session_id == session_id)
                .order_by(IntakeRecord.approved_at.desc())  # type: ignore[attr-defined]
            )
            approved = s.exec(stmt).first()
            if approved is None:
                raise InvalidTransition("no approved record for this session")
            result = self._exporters[target](row.vertical, approved.record, row.id)
            approved.export_target = target
            approved.export_result = result
            approved.exported_at = datetime.now(UTC)
            row.status = "exported"
            row.updated_at = datetime.now(UTC)
            self._audit(s, row.id, "record.exported", target=target)
            s.add(approved)
            s.add(row)
            s.commit()
            return result

    def list_records(self, limit: int = 100) -> list[IntakeRecord]:
        with Session(self._engine) as s:
            stmt = (
                select(IntakeRecord)
                .order_by(IntakeRecord.approved_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )
            return list(s.exec(stmt).all())

    def audit_trail(self, session_id: str) -> list[AuditEvent]:
        with Session(self._engine) as s:
            stmt = (
                select(AuditEvent)
                .where(AuditEvent.session_id == session_id)
                .order_by(AuditEvent.at)  # type: ignore[arg-type]
            )
            return list(s.exec(stmt).all())
