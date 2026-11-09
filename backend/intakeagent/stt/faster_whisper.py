"""Local speech-to-text with faster-whisper (optional extra ``stt-local``).

Runs on CPU with the ``base`` model (roughly real time on a laptop) and on GPU with larger
models. Audio never leaves the process, which is the configuration the compliance docs
recommend for real PHI.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path

from intakeagent.stt.base import TranscriptSegment


class FasterWhisperSTT:
    name = "faster-whisper"

    def __init__(self, model_size: str = "base", device: str = "auto") -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "faster-whisper is not installed. Run `uv sync --extra stt-local`."
            ) from exc
        compute_type = "int8" if device in ("auto", "cpu") else "float16"
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def _transcribe_sync(self, audio: bytes, suffix: str) -> list[TranscriptSegment]:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            path = Path(tmp.name)
        try:
            segments, _info = self._model.transcribe(str(path), vad_filter=True)
            return [
                TranscriptSegment(
                    id=uuid.uuid4().hex[:8],
                    text=s.text.strip(),
                    start_ms=int(s.start * 1000),
                    end_ms=int(s.end * 1000),
                )
                for s in segments
                if s.text.strip()
            ]
        finally:
            path.unlink(missing_ok=True)

    async def transcribe(
        self, audio: bytes, mime_type: str, *, session_id: str, vertical: str
    ) -> list[TranscriptSegment]:
        suffix = ".webm" if "webm" in mime_type else ".ogg" if "ogg" in mime_type else ".wav"
        # Whisper is CPU bound; keep the event loop free for other WebSocket clients.
        return await asyncio.to_thread(self._transcribe_sync, audio, suffix)
