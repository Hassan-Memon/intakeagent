"""Regex-based PHI redaction.

This runs before any transcript is sent to a non-local LLM. It is deliberately simple and
deterministic: every match is replaced with a typed placeholder such as ``[NAME_1]`` or
``[PHONE_2]`` and the placeholder-to-original mapping stays in process memory. When the model
answers, ``rehydrate_record`` swaps the placeholders back so the structured record contains
the real values while the cloud provider only ever saw tokens.

Coverage (HIPAA Safe Harbor identifiers this targets): names, telephone numbers, email
addresses, social security and national identity numbers (US SSN, Pakistan CNIC, UAE
Emirates ID, KSA national ID / Iqama), dates (including dates of birth), and street addresses.

It is a safety net, not a guarantee. For real PHI keep the LLM local (see docs/compliance.md).
Microsoft Presidio can be layered on top via the optional ``presidio`` extra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

# Order matters: more specific identifiers first so a national ID is not half-eaten by the
# phone pattern. Each entry is (label, compiled regex). Group 1, when present, is the span to
# replace; otherwise the whole match is replaced.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("ID", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),  # US SSN
    ("ID", re.compile(r"\b\d{5}-\d{7}-\d\b")),  # Pakistan CNIC
    ("ID", re.compile(r"\b784-\d{4}-\d{7}-\d\b")),  # UAE Emirates ID
    ("ID", re.compile(r"\b[12]\d{9}\b")),  # KSA national ID / Iqama
    (
        "PHONE",
        re.compile(
            r"(?<![\w-])(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?![\w-])"
        ),
    ),
    ("PHONE", re.compile(r"\b0\d{2,4}[\s-]?\d{3}[\s-]?\d{3,4}\b")),  # UK/EU style
    ("DATE", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("DATE", re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")),
    (
        "DATE",
        re.compile(
            rf"\b(?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DATE",
        re.compile(
            rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTHS})\.?,?\s+\d{{4}}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ADDRESS",
        re.compile(
            r"\b\d{1,6}\s+(?:[A-Z][a-zA-Z]+\s+){1,3}"
            r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|"
            r"Way|Place|Pl|Terrace|Crescent)\b\.?"
            r"(?:,?\s*(?:Apt|Apartment|Suite|Unit|#)\s*\w+)?"
            r"(?:,\s*[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)?"
        ),
    ),
    # Names after an explicit introduction. Group 1 is the name.
    (
        "NAME",
        re.compile(
            r"(?i:my name is|my name's|name is|this is|i am|i'm|called|speaking with|patient is|"
            r"client is)\s+([A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+){1,3})"
        ),
    ),
    # Honorific + name.
    (
        "NAME",
        re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+([A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+)?)"),
    ),
    # Relationship + name, e.g. "my manager Karen Blake".
    (
        "NAME",
        re.compile(
            r"\bmy\s+(?:manager|boss|supervisor|wife|husband|partner|spouse|ex|landlord|"
            r"tenant|doctor|lawyer|attorney|brother|sister|mother|father|son|daughter|"
            r"neighbour|neighbor|colleague|friend)\s+([A-Z][a-zA-Z'-]+\s+[A-Z][a-zA-Z'-]+)"
        ),
    ),
]


@dataclass
class Redaction:
    """Result of redacting a piece of text."""

    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original

    @property
    def count(self) -> int:
        return len(self.mapping)


def redact(text: str) -> Redaction:
    """Replace PHI in ``text`` with typed placeholders.

    The same original value always maps to the same placeholder inside one call, so a name
    mentioned three times becomes ``[NAME_1]`` three times and the model can still reason
    about co-reference.
    """
    mapping: dict[str, str] = {}
    reverse: dict[str, str] = {}
    counters: dict[str, int] = {}

    def placeholder_for(label: str, original: str) -> str:
        key = f"{label}:{original.lower()}"
        if key in reverse:
            return reverse[key]
        counters[label] = counters.get(label, 0) + 1
        ph = f"[{label}_{counters[label]}]"
        mapping[ph] = original
        reverse[key] = ph
        return ph

    out = text
    for label, pattern in PATTERNS:
        # Work right-to-left so earlier offsets stay valid while we splice.
        matches = list(pattern.finditer(out))
        for m in reversed(matches):
            if m.lastindex:
                start, end = m.span(1)
            else:
                start, end = m.span()
            original = out[start:end]
            if original.startswith("[") and original.endswith("]"):
                continue  # already a placeholder
            ph = placeholder_for(label, original)
            out = out[:start] + ph + out[end:]
    return Redaction(text=out, mapping=mapping)


def rehydrate_text(text: str, mapping: dict[str, str]) -> str:
    for ph, original in mapping.items():
        text = text.replace(ph, original)
    return text


def rehydrate_record(obj: Any, mapping: dict[str, str]) -> Any:
    """Recursively swap placeholders back inside dicts, lists and strings."""
    if isinstance(obj, str):
        return rehydrate_text(obj, mapping)
    if isinstance(obj, list):
        return [rehydrate_record(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: rehydrate_record(v, mapping) for k, v in obj.items()}
    return obj
