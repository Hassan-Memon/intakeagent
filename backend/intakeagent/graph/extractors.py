"""Transcript to structured record.

Two implementations share one contract: given the full transcript and the vertical, return a
``PatientIntake`` or ``LegalIntake`` whose ``Extracted`` fields carry evidence quotes.

* ``RuleBasedExtractor``: regex and keyword rules. Used in DEMO_MODE and as the fallback when
  no LLM is configured. Good enough to make the demo believable; not meant for production.
* ``LLMExtractor``: ``with_structured_output`` against the Pydantic schema. The transcript is
  redacted first unless the provider is local, and placeholders are re-hydrated afterwards.

``attach_evidence`` turns quotes into character spans against the merged transcript so the UI
can highlight exactly where a value came from.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel

from intakeagent.llm import LLMChoice, get_chat_model
from intakeagent.redaction import redact, rehydrate_record
from intakeagent.schemas import Allergy, Evidence, Extracted, KeyDate, Medication, schema_for
from intakeagent.schemas.base import field_specs

log = logging.getLogger(__name__)

MONTH_NAMES = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}
MONTH_NAMES.update({k[:3]: v for k, v in list(MONTH_NAMES.items())})
MONTH_NAMES["sept"] = 9

MONTHS_RE = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
DATE_RE = re.compile(
    rf"(\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|"
    rf"(?:{MONTHS_RE})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|"
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTHS_RE})\.?,?\s+\d{{4}})",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"(?<![\w-])((?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4})(?![\w-])"
)
EMAIL_RE = re.compile(r"([\w.+-]+@[\w-]+(?:\.[\w-]+)+)")
ADDRESS_RE = re.compile(
    r"(\d{1,6}\s+(?:[A-Z][a-zA-Z]+\s+){1,3}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl)"
    r"\b\.?(?:,\s*[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)?)"
)
NAME_RE = re.compile(
    r"(?i:my name is|my name's|name is|this is|i am|i'm)\s+"
    r"([A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+){1,2})"
)
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def normalize_date(raw: str) -> str:
    """Best effort ISO-8601 (YYYY-MM-DD). Falls back to the raw text."""
    s = raw.strip().rstrip(".,")
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if m:
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yy < 100:
            yy += 1900 if yy > 30 else 2000
        return f"{yy:04d}-{mm:02d}-{dd:02d}"
    m = re.fullmatch(
        rf"({MONTHS_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", s, re.IGNORECASE
    )
    if m:
        return f"{int(m.group(3)):04d}-{MONTH_NAMES[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.fullmatch(
        rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTHS_RE})\.?,?\s+(\d{{4}})",
        s,
        re.IGNORECASE,
    )
    if m:
        return f"{int(m.group(3)):04d}-{MONTH_NAMES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return s


def attach_evidence(record: BaseModel, transcript: str) -> BaseModel:
    """Resolve every evidence quote to a character span in ``transcript``."""
    lowered = transcript.lower()
    for spec in field_specs(type(record)):
        extracted: Extracted[Any] = getattr(record, spec.name)
        for ev in extracted.evidence:
            if not ev.quote:
                continue
            idx = lowered.find(ev.quote.lower())
            if idx >= 0:
                ev.start, ev.end = idx, idx + len(ev.quote)
    return record


def merge_records(previous: BaseModel | None, current: BaseModel) -> BaseModel:
    """Keep earlier values when a re-extraction left a field empty."""
    if previous is None:
        return current
    for spec in field_specs(type(current)):
        cur: Extracted[Any] = getattr(current, spec.name)
        prev: Extracted[Any] = getattr(previous, spec.name)
        if not cur.present and prev.present:
            setattr(current, spec.name, prev)
    return current


class Extractor(Protocol):
    name: str

    def extract(self, transcript: str, vertical: str, previous: BaseModel | None) -> BaseModel: ...


# ---------------------------------------------------------------------------
# Rule based
# ---------------------------------------------------------------------------


def _ex(value: Any, quote: str, confidence: float = 0.6) -> Extracted[Any]:
    return Extracted(value=value, evidence=[Evidence(quote=quote.strip())], confidence=confidence)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _first(pattern: re.Pattern[str], text: str, group: int = 1) -> tuple[str, str] | None:
    m = pattern.search(text)
    if not m:
        return None
    return m.group(group), m.group(0)


class RuleBasedExtractor:
    """Deterministic, offline extractor used by DEMO_MODE."""

    name = "rules"

    def extract(self, transcript: str, vertical: str, previous: BaseModel | None) -> BaseModel:
        schema = schema_for(vertical)  # type: ignore[arg-type]
        data = self._healthcare(transcript) if vertical == "healthcare" else self._legal(transcript)
        record = schema(**data)
        record = merge_records(previous, record)
        return attach_evidence(record, transcript)

    # -- shared -------------------------------------------------------------

    def _contact(self, text: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if hit := _first(PHONE_RE, text):
            out["phone"] = _ex(re.sub(r"[\s.]", "-", hit[0]), hit[1], 0.8)
        if hit := _first(EMAIL_RE, text):
            out["email"] = _ex(hit[0], hit[1], 0.9)
        if hit := _first(ADDRESS_RE, text):
            out["address"] = _ex(hit[0], hit[1], 0.6)
        return out

    def _name(self, text: str) -> Extracted[Any] | None:
        for m in NAME_RE.finditer(text):
            candidate = m.group(1)
            # "I am having" style false positives: require at least two capitalised tokens.
            tokens = candidate.split()
            if all(t[0].isupper() for t in tokens):
                return _ex(candidate, m.group(0), 0.8)
        return None

    # -- healthcare -----------------------------------------------------------

    def _healthcare(self, text: str) -> dict[str, Any]:
        out = self._contact(text)
        if name := self._name(text):
            out["full_name"] = name

        dob = re.search(
            rf"(?:born on|born|date of birth is|dob is|birthday is)\s+{DATE_RE.pattern}",
            text,
            re.IGNORECASE,
        )
        if dob:
            out["date_of_birth"] = _ex(normalize_date(dob.group(1)), dob.group(0), 0.8)

        sex = re.search(r"\b(?:i am|i'm)\s+(?:a\s+)?(male|female|man|woman)\b", text, re.IGNORECASE)
        if sex:
            value = {"man": "male", "woman": "female"}.get(sex.group(1).lower(), sex.group(1))
            out["sex"] = _ex(value.lower(), sex.group(0), 0.6)

        complaint = re.search(
            r"(?:i've had|i have had|i've been having|i have been having|i am having|i'm having|"
            r"i've got|i have got|suffering from|here for|here because of|"
            r"came in (?:for|because of)|"
            r"complaining of|i have)\s+(?:a\s+|an\s+|some\s+)?(.+?)"
            r"(?=\s+(?:since|for the|starting|that started|which started)\b|[,.]|$)",
            text,
            re.IGNORECASE,
        )
        if complaint and not re.match(r"(?:no|any|been|an? appointment)", complaint.group(1), re.I):
            out["chief_complaint"] = _ex(complaint.group(1), complaint.group(0), 0.6)

        onset = re.search(
            r"\b(?:since|started|starting|began|for the (?:last|past))\s+"
            r"((?:[A-Za-z]+\s+){0,2}?(?:yesterday|today|morning|evening|night|afternoon|"
            r"week|weeks|day|days|month|months|year|years|ago|monday|tuesday|wednesday|"
            r"thursday|friday|saturday|sunday)[\w\s]*?)(?=[,.]|$)",
            text,
            re.IGNORECASE,
        )
        if onset:
            out["symptom_onset"] = _ex(onset.group(1).strip(), onset.group(0), 0.6)

        severity = re.search(
            r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
            r"(?:out of|/)\s*(?:10|ten)\b",
            text,
            re.IGNORECASE,
        )
        if severity:
            raw = severity.group(1).lower()
            n = NUMBER_WORDS.get(raw, raw)
            out["symptom_severity"] = _ex(f"{n}/10", severity.group(0), 0.8)

        meds = re.search(
            r"\b(?:i take|i'm taking|i am taking|i'm on|i am on|currently taking|taking)\s+"
            r"(.+?)(?=[.]|$)",
            text,
            re.IGNORECASE,
        )
        if meds:
            items = [p.strip() for p in re.split(r",|\band\b", meds.group(1)) if p.strip()]
            parsed: list[Medication] = []
            for item in items:
                dose = re.search(
                    r"\d+(?:\.\d+)?\s*(?:mg|milligrams?|mcg|micrograms?|units?|ml)", item
                )
                freq = re.search(
                    r"(once|twice|three times|four times)\s+(?:a|per)\s+(day|week)|daily|"
                    r"every (?:morning|night|evening|day)|at bedtime|as needed|weekly",
                    item,
                    re.IGNORECASE,
                )
                name = item
                for seg in (dose, freq):
                    if seg:
                        name = name.replace(seg.group(0), "")
                name = re.sub(r"\s+", " ", name).strip(" ,")
                if not name or name.lower() in {"no medications", "nothing"}:
                    continue
                parsed.append(
                    Medication(
                        name=name,
                        dose=dose.group(0) if dose else None,
                        frequency=freq.group(0) if freq else None,
                    )
                )
            if parsed:
                out["medications"] = _ex([m.model_dump() for m in parsed], meds.group(0), 0.6)
        if re.search(r"\b(?:no|not taking any|don't take any)\s+medications?\b", text, re.I):
            m = re.search(r"[^.]*\bmedications?\b[^.]*", text, re.I)
            out["medications"] = _ex([{"name": "None reported"}], m.group(0) if m else "", 0.7)

        allergy = re.search(
            r"\b(?:allergic to|allergy to|allergies to|allergies (?:are|include))\s+(.+?)(?=[.]|$)",
            text,
            re.IGNORECASE,
        )
        if allergy:
            clause = allergy.group(1)
            reaction = re.search(
                r"(?:it gives me|gives me|causes|i get|makes me|i break out in)\s+([\w\s]+)",
                clause,
                re.IGNORECASE,
            )
            substances = re.split(r",|\band\b", re.split(r",\s*(?:it|which|that)\b", clause)[0])
            parsed_allergies = [
                Allergy(
                    substance=s.strip(),
                    reaction=reaction.group(1).strip() if reaction else None,
                )
                for s in substances
                if s.strip()
            ]
            if parsed_allergies:
                out["allergies"] = _ex(
                    [a.model_dump() for a in parsed_allergies], allergy.group(0), 0.6
                )
        if re.search(r"\bno (?:known )?allergies\b", text, re.I):
            m = re.search(r"[^.]*\bno (?:known )?allergies\b[^.]*", text, re.I)
            out["allergies"] = _ex(
                [{"substance": "No known allergies"}], m.group(0) if m else "", 0.8
            )

        conditions = re.findall(
            r"(?:diagnosed with|history of|i have|i'm|i am)\s+"
            r"((?:type\s*[12]\s+)?(?:diabetes|diabetic|hypertension|high blood pressure|asthma|"
            r"copd|epilepsy|depression|anxiety|arthritis|heart disease|kidney disease|cancer|"
            r"migraines?|hypothyroidism))",
            text,
            re.IGNORECASE,
        )
        if conditions:
            quote = re.search(r"[^.]*(?:diagnosed with|history of)[^.]*", text, re.I)
            out["conditions"] = _ex(
                sorted({c.strip() for c in conditions}),
                quote.group(0) if quote else conditions[0],
                0.5,
            )

        payer = re.search(
            r"\b(?:insurance (?:is|provider is|company is|is with|with)|"
            r"insured (?:by|with|through)|covered (?:by|through)|i have|i'm with)\s+"
            r"([A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*){0,3})",
            text,
        )
        if payer:
            out["insurance_payer"] = _ex(payer.group(1).strip(" ,"), payer.group(0), 0.7)
        member = re.search(
            r"\bmember (?:id|number)(?: is)?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,})", text, re.IGNORECASE
        )
        if member:
            out["insurance_member_id"] = _ex(member.group(1), member.group(0), 0.8)
        return out

    # -- legal ----------------------------------------------------------------

    MATTER_KEYWORDS: dict[str, tuple[str, ...]] = {
        "Employment": (
            "employment",
            "fired",
            "terminated",
            "wrongful termination",
            "employer",
            "discrimination",
            "harassment",
            "unpaid wages",
            "severance",
        ),
        "Personal injury": ("accident", "injured", "injury", "slip", "fell", "crash", "collision"),
        "Contract dispute": ("contract", "breach", "agreement", "unpaid invoice", "vendor"),
        "Family": ("divorce", "custody", "child support", "separation", "alimony"),
        "Real estate": ("landlord", "tenant", "eviction", "lease", "property line"),
        "Immigration": ("visa", "green card", "deportation", "immigration", "asylum"),
        "Criminal defense": ("arrested", "charged with", "dui", "police"),
        "Estate planning": ("will", "estate", "probate", "trust", "inheritance"),
    }

    def _legal(self, text: str) -> dict[str, Any]:
        out = self._contact(text)
        if name := self._name(text):
            out["client_name"] = name

        explicit = re.search(
            r"\b(?:this is an?|it's an?|it is an?|i need help with an?|i have an?)\s+"
            r"([\w\s-]+?)\s+(?:matter|case|issue|dispute|claim)\b",
            text,
            re.IGNORECASE,
        )
        if explicit:
            out["matter_type"] = _ex(explicit.group(1).strip().capitalize(), explicit.group(0), 0.8)
        else:
            lowered = text.lower()
            for label, keys in self.MATTER_KEYWORDS.items():
                hit = next((k for k in keys if k in lowered), None)
                if hit:
                    sentence = next((s for s in _sentences(text) if hit in s.lower()), hit)
                    out["matter_type"] = _ex(label, sentence, 0.5)
                    break

        narrative = [
            s
            for s in _sentences(text)
            if re.search(
                r"\b(?:i was|they|he|she|the company|my employer|happened|after|because)\b",
                s,
                re.IGNORECASE,
            )
            and not NAME_RE.search(s)
        ]
        if narrative:
            out["matter_description"] = _ex(" ".join(narrative[:2]), narrative[0], 0.5)

        opposing = re.search(
            r"\b(?:other party is|opposing party is|against|suing|sued by|dispute with|"
            r"fired (?:by|from)|terminated (?:by|from)|employed by|my employer,?|my landlord,?)\s+"
            r"([A-Z][\w&'.-]*(?:\s+[A-Z][\w&'.-]*){0,4})",
            text,
        )
        if opposing:
            out["opposing_party"] = _ex(opposing.group(1).strip(" ,."), opposing.group(0), 0.7)

        dates: list[KeyDate] = []
        for m in DATE_RE.finditer(text):
            before = text[: m.start()].rstrip()
            # Label = last few words before the date, trimmed at the previous clause boundary.
            clause = re.split(r"[.,;]", before)[-1]
            words = clause.split()[-6:]
            label = " ".join(words).strip() or "date"
            label = re.sub(r"\b(?:on|by|at|in)$", "", label).strip() or "date"
            dates.append(KeyDate(label=label, date=normalize_date(m.group(1))))
        if dates:
            first_sentence = next((s for s in _sentences(text) if DATE_RE.search(s)), "")
            out["key_dates"] = _ex([d.model_dump() for d in dates], first_sentence, 0.6)

        names: list[str] = []
        if "client_name" in out:
            names.append(out["client_name"].value)
        if "opposing_party" in out:
            names.append(out["opposing_party"].value)
        for m in re.finditer(
            r"\bmy\s+(?:manager|boss|supervisor|wife|husband|partner|spouse|ex|landlord|tenant|"
            r"colleague|neighbou?r|business partner)\s+([A-Z][\w'-]+\s+[A-Z][\w'-]+)",
            text,
        ):
            names.append(m.group(1))
        for m in re.finditer(
            r"\b((?:[A-Z][\w&'-]+\s+){1,3}(?:Inc|LLC|Ltd|Limited|Corp|Corporation|Company|Co|"
            r"Group|Logistics|Holdings|Bank|Hospital|Clinic|Partners|Associates)\b\.?)",
            text,
        ):
            names.append(m.group(1).rstrip("."))
        unique: list[str] = []
        for n in names:
            if n and n not in unique:
                unique.append(n)
        if unique:
            quote = (
                out["opposing_party"].evidence[0].quote if "opposing_party" in out else unique[0]
            )
            out["conflict_check_names"] = _ex(unique, quote, 0.6)

        where = re.search(
            r"\b(?:happened|occurred|took place|based|located|live|work)\s+in\s+"
            r"([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?(?:,\s*[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)?)",
            text,
        )
        if where:
            out["jurisdiction"] = _ex(where.group(1).rstrip("."), where.group(0), 0.6)

        urgency = next(
            (
                s
                for s in _sentences(text)
                if re.search(
                    r"\b(?:deadline|court date|hearing|urgent|statute of limitations)\b", s, re.I
                )
            ),
            None,
        )
        if urgency:
            out["urgency"] = _ex(urgency, urgency, 0.5)
        return out


# ---------------------------------------------------------------------------
# LLM based
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an intake coordinator. Read the transcript of a {vertical} intake
conversation and fill the structured record. Rules:
- Only use information stated in the transcript. Leave a field empty if it was not said.
- For every value, copy the exact phrase it came from into evidence[0].quote.
- Tokens like [NAME_1] or [PHONE_1] are redaction placeholders. Copy them verbatim as values.
- Dates in ISO format (YYYY-MM-DD) when the transcript gives a full date.
- confidence is 0.0 to 1.0.
"""


class LLMExtractor:
    """Structured extraction with a chat model, redacting before any non-local call."""

    name = "llm"

    def __init__(self, choice: LLMChoice, *, allow_cloud: bool) -> None:
        self._choice = choice
        self._allow_cloud = allow_cloud
        self._model = get_chat_model(choice)
        self._fallback = RuleBasedExtractor()

    def extract(self, transcript: str, vertical: str, previous: BaseModel | None) -> BaseModel:
        if self._model is None:
            return self._fallback.extract(transcript, vertical, previous)
        if not self._choice.is_local and not self._allow_cloud:
            log.warning("Cloud LLM selected but ALLOW_CLOUD_LLM=0; using rule-based extractor")
            return self._fallback.extract(transcript, vertical, previous)

        schema = schema_for(vertical)  # type: ignore[arg-type]
        mapping: dict[str, str] = {}
        prompt_text = transcript
        if not self._choice.is_local:
            red = redact(transcript)
            prompt_text, mapping = red.text, red.mapping

        try:
            structured = self._model.with_structured_output(schema)
            result = structured.invoke(
                [
                    ("system", SYSTEM_PROMPT.format(vertical=vertical)),
                    ("human", f"Transcript:\n\n{prompt_text}"),
                ]
            )
        except Exception as exc:  # network, schema or provider error
            log.warning("LLM extraction failed (%s); falling back to rules", exc)
            return self._fallback.extract(transcript, vertical, previous)

        data = result.model_dump() if isinstance(result, BaseModel) else dict(result)
        if mapping:
            data = rehydrate_record(data, mapping)
        record = schema(**data)
        record = merge_records(previous, record)
        return attach_evidence(record, transcript)


def build_extractor(choice: LLMChoice, *, allow_cloud: bool) -> Extractor:
    if choice.is_stub:
        return RuleBasedExtractor()
    return LLMExtractor(choice, allow_cloud=allow_cloud)
