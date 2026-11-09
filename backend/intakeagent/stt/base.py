"""STT provider interface and factory.

Each provider receives one complete audio file (the browser restarts MediaRecorder every few
seconds so every blob is a standalone WebM/Opus container, see docs/protocol.md) and returns
timed transcript segments. Offsets are relative to the start of that blob; the session
service shifts them onto the session timeline.
"""

from __future__ import annotations

import importlib.util
from typing import Protocol

from pydantic import BaseModel

from intakeagent.config import Settings


class TranscriptSegment(BaseModel):
    id: str
    text: str
    start_ms: int = 0
    end_ms: int = 0
    final: bool = True


class STTProvider(Protocol):
    name: str

    async def transcribe(
        self, audio: bytes, mime_type: str, *, session_id: str, vertical: str
    ) -> list[TranscriptSegment]: ...


def _faster_whisper_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def get_stt_provider(settings: Settings) -> STTProvider:
    """Pick a provider from settings. DEMO_MODE always wins so demos work without keys."""
    from intakeagent.stt.stub import StubSTT

    if settings.demo_mode or settings.stt_provider == "stub":
        return StubSTT()

    choice = settings.stt_provider
    if choice == "auto":
        if _faster_whisper_available():
            choice = "faster_whisper"
        elif settings.groq_api_key:
            choice = "groq"
        else:
            return StubSTT()

    if choice == "faster_whisper":
        from intakeagent.stt.faster_whisper import FasterWhisperSTT

        return FasterWhisperSTT(model_size=settings.faster_whisper_model)
    if choice == "groq":
        from intakeagent.stt.groq import GroqWhisperSTT

        return GroqWhisperSTT(api_key=settings.groq_api_key)
    return StubSTT()
