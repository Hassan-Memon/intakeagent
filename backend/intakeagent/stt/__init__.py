"""Speech-to-text providers behind one small interface."""

from intakeagent.stt.base import STTProvider, TranscriptSegment, get_stt_provider

__all__ = ["STTProvider", "TranscriptSegment", "get_stt_provider"]
