"""Scripted STT for DEMO_MODE.

Every audio chunk the browser sends advances a per-session script, so you can click the mic,
say anything (or nothing) and watch a realistic intake unfold with no model and no API key.
The scripts intentionally exercise every required field in the schemas, in an order that lets
the missing-field detector ask real follow-up questions along the way.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from intakeagent.stt.base import TranscriptSegment

SCRIPTS: dict[str, list[str]] = {
    "healthcare": [
        "Hi, my name is Sarah Mitchell and I was born on March 4th, 1986.",
        "I've had a sharp pain in my lower right side since Tuesday evening, "
        "it's about a six out of ten.",
        "I take metformin 500 milligrams twice a day, lisinopril 10 milligrams every morning "
        "and amoxicillin 500 milligrams three times a day.",
        "I'm allergic to penicillin, it gives me hives.",
        "My phone number is 415-555-0134 and my insurance is Blue Shield, member ID BS88213.",
        "I live at 220 Maple Street, Oakland. I was diagnosed with type 2 diabetes in 2019.",
    ],
    "legal": [
        "My name is Daniel Okafor, you can reach me at 212-555-0188 or daniel.okafor@example.com.",
        "This is an employment matter. I was fired from Northwind Logistics on June 12th, 2025 "
        "after I reported safety violations to HR.",
        "The other party is Northwind Logistics and my manager Karen Blake.",
        "I received a severance letter on June 20th, 2025 with a deadline to sign by "
        "July 15th, 2025.",
        "It happened in Newark, New Jersey. The deadline is what makes this urgent.",
    ],
}

# Roughly how long each scripted line takes to say, so timelines look believable.
LINE_DURATION_MS = 4000


class StubSTT:
    name = "stub"

    def __init__(self) -> None:
        self._cursor: dict[str, int] = defaultdict(int)

    async def transcribe(
        self, audio: bytes, mime_type: str, *, session_id: str, vertical: str
    ) -> list[TranscriptSegment]:
        script = SCRIPTS.get(vertical, SCRIPTS["healthcare"])
        idx = self._cursor[session_id]
        if idx >= len(script):
            return []  # script exhausted; the user can still type
        self._cursor[session_id] = idx + 1
        return [
            TranscriptSegment(
                id=uuid.uuid4().hex[:8],
                text=script[idx],
                start_ms=0,
                end_ms=LINE_DURATION_MS,
            )
        ]
