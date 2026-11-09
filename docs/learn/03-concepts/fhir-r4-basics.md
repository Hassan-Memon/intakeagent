# FHIR R4 basics

## What FHIR is

FHIR (Fast Healthcare Interoperability Resources) is HL7's standard for exchanging health
data as JSON (or XML) over a REST API. R4 is the version almost every EHR and national
programme targets today (US Core, UK Core, Saudi NPHIES). If your system speaks FHIR R4, it
can talk to Epic, Cerner, HAPI, Azure Health Data Services and the rest without a custom
connector.

## Resources

Everything is a **resource**: a JSON object with a `resourceType` and a fixed set of elements.
IntakeAgent produces seven kinds (`backend/intakeagent/exporters/fhir.py`):

- `Patient`: who. Name, birthDate, gender, telecom (phone, email), address.
- `Encounter`: the visit. `status`, `class` (AMB for ambulatory), `subject`, `period`,
  `reasonCode`.
- `Condition`: a problem or diagnosis. We emit one for the chief complaint (category
  `encounter-diagnosis`) and one per known condition (`problem-list-item`).
- `AllergyIntolerance`: substance plus `reaction.manifestation`.
- `MedicationStatement`: what the patient says they take, with `dosage.text`.
- `Coverage`: insurance payer and subscriber id.
- `Bundle`: a container for the others.

## Data types you will meet

- **CodeableConcept**: `{"coding": [{"system", "code", "display"}], "text"}`. The `text` is
  free text; `coding` is a terminology code (SNOMED CT, RxNorm, ICD-10). We emit `text` only,
  which is valid, and leave coding to a later terminology step.
- **Reference**: `{"reference": "Patient/123"}` or, inside a transaction, a `urn:uuid:` that
  points at another entry's `fullUrl`.
- **Period**, **HumanName**, **ContactPoint**, **Address**: small structured types with
  predictable fields.
- Dates are strings: `birthDate` is `YYYY-MM-DD`; `period.start` is an ISO instant.

## Required codes

Some elements must come from a fixed value set. `Encounter.status` must be one of
`planned | arrived | triaged | in-progress | onleave | finished | cancelled | ...`;
`Condition.clinicalStatus` uses the `condition-clinical` code system; `AllergyIntolerance.
clinicalStatus` uses `allergyintolerance-clinical`. `fhir.resources` enforces these at
construction time, which is why the exporter is written against its classes rather than
dictionaries (see ADR-0002).

## Bundles and transactions

A `Bundle` with `type: "transaction"` is a list of entries, each with a `resource` and a
`request` (`method: POST`, `url: Patient`). The server applies all of them atomically and
rewrites `urn:uuid:` references to real ids. The response is a `transaction-response` Bundle
with one entry per input containing the new location. This is how you create a patient and
their conditions in one call without knowing the patient id in advance.

## Validation

`fhir.resources` is Pydantic. `Patient(name=[...], birthDate="1986-03-04")` validates
cardinality and types; `Bundle.model_validate(dict)` re-validates a whole Bundle, which the
tests do (`tests/test_exporters.py`). Serialise with
`model_dump(mode="json", by_alias=True, exclude_none=True)`: `mode="json"` turns dates into
strings, `by_alias` emits FHIR's camelCase and `class` (a Python keyword), and `exclude_none`
keeps the JSON clean.

## Talking to a server

`POST {base}/` with `Content-Type: application/fhir+json` and the transaction Bundle as the
body. HAPI's public sandbox at `https://hapi.fhir.org/baseR4` accepts this; it is for synthetic
data only, which is why `FHIR_PUSH` defaults to off. Other useful calls: `GET
{base}/Patient?identifier=urn:intakeagent:session|{id}` to find what you created, and
`GET {base}/metadata` to read a server's CapabilityStatement.

## Where profiles come in

US Core, UK Core and Saudi Core are **profiles**: constraints on base resources (must-support
elements, required code systems). The exporter produces base R4, which these servers accept
but may not consider conformant to their profile. Adding a profile means adding `meta.profile`
and the required codings; the structure does not change.
