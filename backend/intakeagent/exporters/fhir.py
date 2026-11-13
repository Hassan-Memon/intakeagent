"""FHIR R4 exporter.

Builds a transaction ``Bundle`` with Patient, Encounter, Condition (chief complaint and prior
conditions), AllergyIntolerance, MedicationStatement and Coverage resources. Every resource is
validated through ``fhir.resources`` (R4B profile, wire-compatible with R4 servers such as the
public HAPI sandbox). Resources reference each other with ``urn:uuid:`` full URLs so a server
can assign real ids on commit.

Pushing to a server is opt-in (``FHIR_PUSH=1``) because the public HAPI sandbox is for test
data only and because sending PHI anywhere is a deliberate decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fhir.resources.R4B.allergyintolerance import AllergyIntolerance
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.condition import Condition
from fhir.resources.R4B.coverage import Coverage
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.medicationstatement import MedicationStatement
from fhir.resources.R4B.patient import Patient

from intakeagent.schemas import PatientIntake


def _urn() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def _entry(resource: Any, full_url: str) -> dict[str, Any]:
    return {
        "fullUrl": full_url,
        "resource": resource.model_dump(mode="json", by_alias=True, exclude_none=True),
        "request": {"method": "POST", "url": resource.get_resource_type()},
    }


def _split_name(full: str) -> tuple[list[str], str]:
    parts = full.strip().split()
    if len(parts) == 1:
        return [], parts[0]
    return parts[:-1], parts[-1]


def _valid_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        return None


def _concept(text: str, codes: dict[str, Any]) -> dict[str, Any]:
    """CodeableConcept with the patient's words as ``text`` plus any reviewer-accepted coding.

    ``codes`` is keyed by the exact text that was coded; if the text was edited after the code
    was accepted there is no key match and only ``text`` is exported.
    """
    concept: dict[str, Any] = {"text": text}
    coding = codes.get(text)
    if coding is not None:
        c = coding.model_dump() if hasattr(coding, "model_dump") else dict(coding)
        concept["coding"] = [c]
    return concept


def build_bundle(record: PatientIntake, session_id: str) -> dict[str, Any]:
    """Build and validate a transaction Bundle from a PatientIntake.

    Medications and allergies carry RxNorm codings, and the chief complaint and conditions
    carry ICD-10-CM codings, when a reviewer accepted them (``record.codes``). The patient's own
    words always stay in ``text``.
    """
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    codes = record.codes
    patient_url = _urn()
    encounter_url = _urn()
    entries: list[dict[str, Any]] = []

    given, family = _split_name(record.full_name.value or "Unknown")
    telecom = []
    if record.phone.value:
        telecom.append({"system": "phone", "value": record.phone.value, "use": "mobile"})
    if record.email.value:
        telecom.append({"system": "email", "value": record.email.value})
    gender = None
    if record.sex.value and record.sex.value.lower() in {"male", "female", "other", "unknown"}:
        gender = record.sex.value.lower()
    patient = Patient(
        identifier=[{"system": "urn:intakeagent:session", "value": session_id}],
        name=[{"use": "official", "family": family, "given": given or None}],
        birthDate=_valid_date(record.date_of_birth.value),
        gender=gender,
        telecom=telecom or None,
        address=[{"text": record.address.value}] if record.address.value else None,
    )
    entries.append(_entry(patient, patient_url))

    encounter = Encounter(
        status="arrived",
        **{
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": "AMB",
                "display": "ambulatory",
            }
        },
        subject={"reference": patient_url},
        period={"start": now},
        reasonCode=(
            [_concept(record.chief_complaint.value, codes.chief_complaint)]
            if record.chief_complaint.value
            else None
        ),
    )
    entries.append(_entry(encounter, encounter_url))

    if record.chief_complaint.value:
        condition = Condition(
            clinicalStatus={
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": "active",
                    }
                ]
            },
            category=[
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                            "code": "encounter-diagnosis",
                        }
                    ]
                }
            ],
            code=_concept(record.chief_complaint.value, codes.chief_complaint),
            subject={"reference": patient_url},
            encounter={"reference": encounter_url},
            onsetString=record.symptom_onset.value or None,
            note=(
                [{"text": f"Severity {record.symptom_severity.value}"}]
                if record.symptom_severity.value
                else None
            ),
        )
        entries.append(_entry(condition, _urn()))

    for name in record.conditions.value or []:
        entries.append(
            _entry(
                Condition(
                    clinicalStatus={
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    category=[
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                    "code": "problem-list-item",
                                }
                            ]
                        }
                    ],
                    code=_concept(name, codes.conditions),
                    subject={"reference": patient_url},
                ),
                _urn(),
            )
        )

    for allergy in record.allergies.value or []:
        substance = allergy.substance if hasattr(allergy, "substance") else allergy["substance"]
        reaction = allergy.reaction if hasattr(allergy, "reaction") else allergy.get("reaction")
        if substance.lower().startswith("no known"):
            continue
        entries.append(
            _entry(
                AllergyIntolerance(
                    clinicalStatus={
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    code=_concept(substance, codes.allergies),
                    patient={"reference": patient_url},
                    reaction=([{"manifestation": [{"text": reaction}]}] if reaction else None),
                ),
                _urn(),
            )
        )

    for med in record.medications.value or []:
        name = med.name if hasattr(med, "name") else med["name"]
        dose = med.dose if hasattr(med, "dose") else med.get("dose")
        freq = med.frequency if hasattr(med, "frequency") else med.get("frequency")
        if name.lower().startswith("none"):
            continue
        dosage_text = " ".join(x for x in (dose, freq) if x) or None
        entries.append(
            _entry(
                MedicationStatement(
                    status="active",
                    medicationCodeableConcept=_concept(name, codes.medications),
                    subject={"reference": patient_url},
                    context={"reference": encounter_url},
                    dosage=[{"text": dosage_text}] if dosage_text else None,
                ),
                _urn(),
            )
        )

    if record.insurance_payer.value:
        entries.append(
            _entry(
                Coverage(
                    status="active",
                    beneficiary={"reference": patient_url},
                    subscriberId=record.insurance_member_id.value or None,
                    payor=[{"display": record.insurance_payer.value}],
                ),
                _urn(),
            )
        )

    bundle = Bundle(type="transaction", entry=entries)
    return bundle.model_dump(mode="json", by_alias=True, exclude_none=True)


class FhirExporter:
    """Build a Bundle and optionally POST it to a FHIR server."""

    name = "fhir"

    def __init__(self, base_url: str, push: bool) -> None:
        self._base_url = base_url.rstrip("/")
        self._push = push

    def export(self, record: PatientIntake, session_id: str) -> dict[str, Any]:
        bundle = build_bundle(record, session_id)
        result: dict[str, Any] = {
            "target": "fhir",
            "mode": "push" if self._push else "dry-run",
            "server": self._base_url,
            "payload": bundle,
            "resource_count": len(bundle.get("entry", [])),
        }
        if not self._push:
            return result
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                self._base_url,
                json=bundle,
                headers={"Content-Type": "application/fhir+json"},
            )
        result["status_code"] = resp.status_code
        try:
            result["response"] = resp.json()
        except ValueError:
            result["response"] = {"text": resp.text[:2000]}
        return result
