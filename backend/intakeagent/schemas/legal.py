"""LegalIntake: what a law firm needs to open a matter and run a conflict check."""

from __future__ import annotations

from pydantic import BaseModel

from intakeagent.schemas.base import Extracted, intake_field


class KeyDate(BaseModel):
    label: str
    date: str


class LegalIntake(BaseModel):
    """Structured legal intake. Field order is the order questions are asked."""

    client_name: Extracted[str] = intake_field(
        required=True,
        question="Could you tell me your full name, please?",
        group="client",
    )
    phone: Extracted[str] = intake_field(
        required=True,
        question="What is the best phone number to reach you?",
        group="client",
    )
    email: Extracted[str] = intake_field(
        required=False,
        question="Do you have an email address we can use?",
        group="client",
    )
    address: Extracted[str] = intake_field(
        required=False,
        question="What is your mailing address?",
        group="client",
    )
    matter_type: Extracted[str] = intake_field(
        required=True,
        question="In a few words, what kind of legal matter is this? For example a contract "
        "dispute, employment issue, personal injury or family matter.",
        description="Practice area",
        group="matter",
    )
    matter_description: Extracted[str] = intake_field(
        required=True,
        question="Please describe what happened in your own words.",
        group="matter",
    )
    opposing_party: Extracted[str] = intake_field(
        required=True,
        question="Who is the other party involved? A person or a company name is fine.",
        group="matter",
    )
    jurisdiction: Extracted[str] = intake_field(
        required=False,
        question="Which city or state did this take place in?",
        group="matter",
    )
    key_dates: Extracted[list[KeyDate]] = intake_field(
        required=True,
        question="Are there any important dates, such as when the incident happened, a "
        "contract date or a deadline you have been given?",
        group="matter",
    )
    conflict_check_names: Extracted[list[str]] = intake_field(
        required=True,
        question="Please list the full names of everyone involved so we can run a conflict "
        "check, including companies.",
        group="conflicts",
    )
    urgency: Extracted[str] = intake_field(
        required=False,
        question="Is there a deadline or court date coming up that makes this urgent?",
        group="matter",
    )
