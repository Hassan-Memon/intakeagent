"""Structured intake schemas.

Both verticals share one shape: every captured field is an ``Extracted[T]`` that carries the
value, the transcript evidence it came from, and a confidence. Field-level metadata
(``required_for_intake`` and ``question``) lives in ``json_schema_extra`` so the graph can
compute missing fields and phrase the next question without a second source of truth.
"""

from intakeagent.schemas.base import (
    Coding,
    Evidence,
    Extracted,
    FieldSpec,
    Vertical,
    field_specs,
    intake_field,
    missing_required,
)
from intakeagent.schemas.legal import KeyDate, LegalIntake
from intakeagent.schemas.patient import Allergy, Medication, PatientIntake, ReviewerCodes

SCHEMAS = {"healthcare": PatientIntake, "legal": LegalIntake}


def schema_for(vertical: Vertical) -> type[PatientIntake] | type[LegalIntake]:
    return SCHEMAS[vertical]


__all__ = [
    "Allergy",
    "Coding",
    "Evidence",
    "Extracted",
    "FieldSpec",
    "KeyDate",
    "LegalIntake",
    "Medication",
    "PatientIntake",
    "ReviewerCodes",
    "SCHEMAS",
    "Vertical",
    "field_specs",
    "intake_field",
    "missing_required",
    "schema_for",
]
