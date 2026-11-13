"""PatientIntake: what a clinic front desk needs before the clinician walks in."""

from __future__ import annotations

from pydantic import BaseModel, Field

from intakeagent.schemas.base import Coding, Extracted, intake_field


class Medication(BaseModel):
    name: str
    dose: str | None = None
    frequency: str | None = None


class Allergy(BaseModel):
    substance: str
    reaction: str | None = None


class ReviewerCodes(BaseModel):
    """Standard codes a reviewer accepted on the review screen.

    Each map is keyed by the exact text it codes (a medication name, an allergy substance, the
    chief complaint, a condition). If the reviewer later edits that text, the key no longer
    matches and the stale code is simply not exported, rather than exported against the wrong
    words. Only a person sets these; extractors never do.
    """

    medications: dict[str, Coding] = Field(default_factory=dict)
    allergies: dict[str, Coding] = Field(default_factory=dict)
    chief_complaint: dict[str, Coding] = Field(default_factory=dict)
    conditions: dict[str, Coding] = Field(default_factory=dict)


class PatientIntake(BaseModel):
    """Structured healthcare intake. Field order is the order questions are asked."""

    full_name: Extracted[str] = intake_field(
        required=True,
        question="Could you tell me your full name, please?",
        description="Patient legal name",
        group="demographics",
    )
    date_of_birth: Extracted[str] = intake_field(
        required=True,
        question="What is your date of birth?",
        description="ISO date if possible",
        group="demographics",
    )
    sex: Extracted[str] = intake_field(
        required=False,
        question="What sex is recorded on your ID?",
        group="demographics",
    )
    phone: Extracted[str] = intake_field(
        required=True,
        question="What is the best phone number to reach you?",
        group="demographics",
    )
    email: Extracted[str] = intake_field(
        required=False,
        question="Do you have an email address we can use for appointment reminders?",
        group="demographics",
    )
    address: Extracted[str] = intake_field(
        required=False,
        question="What is your home address?",
        group="demographics",
    )
    chief_complaint: Extracted[str] = intake_field(
        required=True,
        question="What brings you in today?",
        description="Main reason for the visit in the patient's words",
        group="visit",
    )
    symptom_onset: Extracted[str] = intake_field(
        required=True,
        question="When did this start?",
        group="visit",
    )
    symptom_severity: Extracted[str] = intake_field(
        required=False,
        question="On a scale of one to ten, how severe is it right now?",
        group="visit",
    )
    medications: Extracted[list[Medication]] = intake_field(
        required=True,
        question="Are you currently taking any medications? Please name them and the dose.",
        group="history",
    )
    allergies: Extracted[list[Allergy]] = intake_field(
        required=True,
        question="Do you have any allergies to medications, foods or latex?",
        group="history",
    )
    conditions: Extracted[list[str]] = intake_field(
        required=False,
        question="Do you have any ongoing medical conditions we should know about?",
        group="history",
    )
    insurance_payer: Extracted[str] = intake_field(
        required=True,
        question="Who is your insurance provider?",
        group="insurance",
    )
    insurance_member_id: Extracted[str] = intake_field(
        required=False,
        question="What is the member ID on your insurance card?",
        group="insurance",
    )
    codes: ReviewerCodes = Field(
        default_factory=ReviewerCodes,
        description="RxNorm and ICD-10-CM codes accepted by the reviewer. Not extracted.",
    )
