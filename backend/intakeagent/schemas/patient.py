"""PatientIntake: what a clinic front desk needs before the clinician walks in."""

from __future__ import annotations

from pydantic import BaseModel

from intakeagent.schemas.base import Extracted, intake_field


class Medication(BaseModel):
    name: str
    dose: str | None = None
    frequency: str | None = None


class Allergy(BaseModel):
    substance: str
    reaction: str | None = None


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
