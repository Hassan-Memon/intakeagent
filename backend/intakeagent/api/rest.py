"""REST routes. See docs/protocol.md for the WebSocket side."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from intakeagent.api.service import IntakeService, InvalidTransition, SessionNotFound
from intakeagent.db.models import IntakeRecord, IntakeSession
from intakeagent.schemas import field_specs, schema_for

router = APIRouter()


def _service(request: Request) -> IntakeService:
    return request.app.state.service


class CreateSessionBody(BaseModel):
    vertical: Literal["healthcare", "legal"]


class ApproveBody(BaseModel):
    record: dict[str, Any] | None = Field(
        default=None, description="Edited record (full PatientIntake/LegalIntake shape)."
    )
    export_target: Literal["fhir", "clio"] | None = None
    approved_by: str = "front-desk"
    acknowledged_flags: list[str] = Field(
        default_factory=list,
        description="Ids of verification flags the reviewer saw before approving (audited).",
    )


class VerifyBody(BaseModel):
    record: dict[str, Any] | None = Field(
        default=None, description="Edited record to check; omit to check the stored record."
    )


class TextBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def session_out(row: IntakeSession) -> dict[str, Any]:
    specs = field_specs(schema_for(row.vertical))  # type: ignore[arg-type]
    return {
        "id": row.id,
        "vertical": row.vertical,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "transcript": row.transcript,
        "transcript_segments": row.transcript_segments,
        "record": row.record,
        "missing_fields": row.missing_fields,
        "next_question": row.next_question,
        "next_field": row.next_field,
        "field_specs": [s.model_dump() for s in specs],
    }


def record_out(row: IntakeRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "vertical": row.vertical,
        "record": row.record,
        "approved_at": row.approved_at.isoformat(),
        "approved_by": row.approved_by,
        "export_target": row.export_target,
        "exported_at": row.exported_at.isoformat() if row.exported_at else None,
        "export_result": row.export_result,
    }


@router.post("/sessions", status_code=201)
def create_session(body: CreateSessionBody, request: Request) -> dict[str, Any]:
    return session_out(_service(request).create_session(body.vertical))


@router.get("/sessions")
def list_sessions(request: Request) -> list[dict[str, Any]]:
    return [session_out(r) for r in _service(request).list_sessions()]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict[str, Any]:
    try:
        return session_out(_service(request).get_session(session_id))
    except SessionNotFound as exc:
        raise HTTPException(404, "session not found") from exc


@router.post("/sessions/{session_id}/text")
def add_text(session_id: str, body: TextBody, request: Request) -> dict[str, Any]:
    """Typed utterance (accessibility fallback). Same graph path as audio."""
    try:
        result = _service(request).add_text(session_id, body.text)
    except SessionNotFound as exc:
        raise HTTPException(404, "session not found") from exc
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "record": result.record,
        "missing_fields": result.missing_fields,
        "next_question": result.next_question,
        "next_field": result.next_field,
    }


@router.post("/sessions/{session_id}/finish")
def finish(session_id: str, request: Request) -> dict[str, Any]:
    try:
        result = _service(request).finish(session_id)
    except SessionNotFound as exc:
        raise HTTPException(404, "session not found") from exc
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "status": result.status,
        "missing_fields": result.missing_fields,
        "interrupt": result.interrupt,
    }


@router.post("/sessions/{session_id}/approve")
def approve(session_id: str, body: ApproveBody, request: Request) -> dict[str, Any]:
    try:
        approved, result = _service(request).approve(
            session_id,
            record=body.record,
            export_target=body.export_target,
            approved_by=body.approved_by,
            acknowledged_flags=body.acknowledged_flags,
        )
    except SessionNotFound as exc:
        raise HTTPException(404, "session not found") from exc
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, f"invalid record: {exc}") from exc
    return {"status": result.status, "record": record_out(approved)}


@router.post("/sessions/{session_id}/verify")
def verify(session_id: str, request: Request, body: VerifyBody | None = None) -> dict[str, Any]:
    """Reference-data checks: RxNorm, ICD-10-CM and allergy flags, or sanctions screening."""
    try:
        return _service(request).verify(session_id, body.record if body else None)
    except SessionNotFound as exc:
        raise HTTPException(404, "session not found") from exc
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, f"invalid record: {exc}") from exc


@router.post("/sessions/{session_id}/export")
def export(
    session_id: str,
    request: Request,
    target: Literal["fhir", "clio"] = Query(...),
) -> dict[str, Any]:
    try:
        return _service(request).export(session_id, target)
    except SessionNotFound as exc:
        raise HTTPException(404, "session not found") from exc
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/sessions/{session_id}/audit")
def audit(session_id: str, request: Request) -> list[dict[str, Any]]:
    return [
        {"at": e.at.isoformat(), "actor": e.actor, "action": e.action, "detail": e.detail}
        for e in _service(request).audit_trail(session_id)
    ]


@router.get("/records")
def list_records(request: Request) -> list[dict[str, Any]]:
    return [record_out(r) for r in _service(request).list_records()]


@router.get("/schemas/{vertical}")
def schema(vertical: Literal["healthcare", "legal"]) -> dict[str, Any]:
    """Field metadata the review UI uses to render the form."""
    return {
        "vertical": vertical,
        "fields": [s.model_dump() for s in field_specs(schema_for(vertical))],
        "json_schema": schema_for(vertical).model_json_schema(),
    }
