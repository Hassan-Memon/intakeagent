"""Groq hosted Whisper (whisper-large-v3), free tier.

Groq exposes an OpenAI-compatible audio endpoint. We ask for ``verbose_json`` to get segment
timestamps. Note: audio leaves your machine with this provider. The compliance docs flag this;
use faster-whisper for regulated deployments.
"""

from __future__ import annotations

import uuid

import httpx

from intakeagent.stt.base import TranscriptSegment

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class GroqWhisperSTT:
    name = "groq-whisper-large-v3"

    def __init__(self, api_key: str, model: str = "whisper-large-v3") -> None:
        self._api_key = api_key
        self._model = model

    async def transcribe(
        self, audio: bytes, mime_type: str, *, session_id: str, vertical: str
    ) -> list[TranscriptSegment]:
        ext = "webm" if "webm" in mime_type else "ogg" if "ogg" in mime_type else "wav"
        files = {"file": (f"chunk.{ext}", audio, mime_type)}
        data = {"model": self._model, "response_format": "verbose_json"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files=files,
                data=data,
            )
            resp.raise_for_status()
        payload = resp.json()
        segments = payload.get("segments") or []
        if not segments and payload.get("text"):
            return [TranscriptSegment(id=uuid.uuid4().hex[:8], text=payload["text"].strip())]
        return [
            TranscriptSegment(
                id=uuid.uuid4().hex[:8],
                text=str(s.get("text", "")).strip(),
                start_ms=int(float(s.get("start", 0)) * 1000),
                end_ms=int(float(s.get("end", 0)) * 1000),
            )
            for s in segments
            if str(s.get("text", "")).strip()
        ]
