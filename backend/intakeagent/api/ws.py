"""WebSocket endpoint: /ws/intake/{session_id}

One connection per intake session. The browser sends small JSON control frames and binary
audio frames (each a complete WebM/Opus file); the server streams back transcript segments,
the evolving structured record and the agent's next question. Full message catalogue in
docs/protocol.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from intakeagent.api.service import IntakeService, InvalidTransition, SessionNotFound, TurnResult
from intakeagent.stt.base import STTProvider

log = logging.getLogger(__name__)
router = APIRouter()

MAX_AUDIO_BYTES = 8 * 1024 * 1024  # a 10 s Opus chunk is ~100 KB; this is a generous cap


async def _send(ws: WebSocket, payload: dict[str, Any]) -> None:
    if ws.client_state == WebSocketState.CONNECTED:
        await ws.send_text(json.dumps(payload))


async def _send_turn(ws: WebSocket, result: TurnResult) -> None:
    await _send(
        ws,
        {
            "type": "extraction",
            "record": result.record,
            "missing_fields": result.missing_fields,
        },
    )
    if result.next_question:
        await _send(
            ws, {"type": "question", "text": result.next_question, "field": result.next_field}
        )


@router.websocket("/ws/intake/{session_id}")
async def intake_socket(ws: WebSocket, session_id: str) -> None:
    service: IntakeService = ws.app.state.service
    stt: STTProvider = ws.app.state.stt

    try:
        session = await asyncio.to_thread(service.get_session, session_id)
    except SessionNotFound:
        await ws.close(code=4404, reason="session not found")
        return

    await ws.accept()
    await _send(
        ws,
        {
            "type": "ready",
            "session_id": session.id,
            "vertical": session.vertical,
            "status": session.status,
            "stt": stt.name,
            "question": session.next_question,
            "record": session.record,
            "missing_fields": session.missing_fields,
        },
    )

    mime_type = "audio/webm;codecs=opus"
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break

            if message.get("bytes"):
                audio: bytes = message["bytes"]
                if len(audio) > MAX_AUDIO_BYTES:
                    await _send(
                        ws, {"type": "error", "code": "too_large", "message": "chunk too big"}
                    )
                    continue
                await _send(ws, {"type": "status", "state": "transcribing"})
                try:
                    segments = await stt.transcribe(
                        audio, mime_type, session_id=session.id, vertical=session.vertical
                    )
                except Exception as exc:  # provider error: keep the session alive
                    log.exception("STT failed")
                    await _send(ws, {"type": "error", "code": "stt_failed", "message": str(exc)})
                    await _send(ws, {"type": "status", "state": "listening"})
                    continue
                if not segments:
                    await _send(ws, {"type": "status", "state": "listening"})
                    continue
                await _send(ws, {"type": "status", "state": "thinking"})
                try:
                    result = await asyncio.to_thread(service.add_segments, session.id, segments)
                except InvalidTransition as exc:
                    await _send(ws, {"type": "error", "code": "invalid_state", "message": str(exc)})
                    continue
                for seg in result.new_segments:
                    await _send(ws, {"type": "transcript", "segment": seg})
                await _send_turn(ws, result)
                await _send(ws, {"type": "status", "state": "listening"})
                continue

            raw = message.get("text")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "code": "bad_json", "message": "invalid JSON"})
                continue

            kind = data.get("type")
            if kind == "ping":
                await _send(ws, {"type": "pong"})
            elif kind == "audio_meta":
                mime_type = str(data.get("mime", mime_type))
            elif kind == "text":
                text = str(data.get("text", "")).strip()
                if not text:
                    continue
                await _send(ws, {"type": "status", "state": "thinking"})
                try:
                    result = await asyncio.to_thread(service.add_text, session.id, text)
                except InvalidTransition as exc:
                    await _send(ws, {"type": "error", "code": "invalid_state", "message": str(exc)})
                    continue
                for seg in result.new_segments:
                    await _send(ws, {"type": "transcript", "segment": seg})
                await _send_turn(ws, result)
                await _send(ws, {"type": "status", "state": "listening"})
            elif kind == "finish":
                await _send(ws, {"type": "status", "state": "finishing"})
                try:
                    result = await asyncio.to_thread(service.finish, session.id)
                except InvalidTransition as exc:
                    await _send(ws, {"type": "error", "code": "invalid_state", "message": str(exc)})
                    continue
                await _send(
                    ws,
                    {
                        "type": "awaiting_approval",
                        "session_id": session.id,
                        "record": result.record,
                        "missing_fields": result.missing_fields,
                        "review_url": f"/review/{session.id}",
                    },
                )
                await _send(ws, {"type": "status", "state": "awaiting_approval"})
            else:
                await _send(
                    ws, {"type": "error", "code": "unknown_type", "message": f"unknown type {kind}"}
                )
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - defensive
        log.exception("WebSocket handler crashed")
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close(code=1011)
