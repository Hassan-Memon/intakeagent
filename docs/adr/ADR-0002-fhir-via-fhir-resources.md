# ADR-0002: FHIR R4 export through fhir.resources

- Status: accepted
- Date: 2026-11-09
- Deciders: Hassan Memon

## Context and problem statement

Healthcare intake must land in an EHR or interoperability layer. FHIR R4 is the common
interchange standard (US Core, UK Core, Saudi NPHIES all build on it). The question is how
to produce FHIR: hand-built dictionaries, a code generator, or a validating library.

## Decision drivers

- Correctness: a malformed resource is rejected by servers and erodes trust.
- Developer speed: the owner should not need to memorise 150 resource definitions.
- Pydantic everywhere: the rest of the backend is Pydantic v2, so a Pydantic FHIR model fits.
- Free sandbox for demos: HAPI FHIR's public R4 server accepts transaction Bundles.

## Considered options

1. `fhir.resources` (Pydantic models for every FHIR resource, R4B and R5 packages).
2. Hand-written dictionaries validated only by the target server.
3. `fhirclient` (SMART on FHIR client library) with its own models.
4. Generate from StructureDefinitions with a custom tool.

## Decision outcome

Chosen option 1. `fhir.resources` validates cardinality, data types, codes and references at
construction time, serialises to spec-compliant JSON with `model_dump(mode="json",
by_alias=True, exclude_none=True)`, and is plain Pydantic, so it composes with the rest of
the code. We use the R4B package, which is wire-compatible with R4 servers; HAPI's `baseR4`
accepts the output. Implementation: `backend/intakeagent/exporters/fhir.py`.

### Resource mapping

| Intake field(s) | FHIR resource |
| --- | --- |
| full_name, date_of_birth, sex, phone, email, address | `Patient` |
| visit itself | `Encounter` (status arrived, class AMB, reasonCode = chief complaint) |
| chief_complaint, symptom_onset, symptom_severity | `Condition` (category encounter-diagnosis, onsetString, note) |
| conditions | one `Condition` each (problem-list-item) |
| allergies | `AllergyIntolerance` with reaction.manifestation |
| medications | `MedicationStatement` with dosage.text |
| insurance_payer, insurance_member_id | `Coverage` |

Resources are wrapped in a `transaction` Bundle with `urn:uuid:` fullUrls so the server
assigns ids and resolves internal references atomically.

### Consequences

- Good: invalid resources fail locally in tests (`tests/test_exporters.py`) rather than at
  the server; the test suite re-validates the whole Bundle through `Bundle.model_validate`.
- Good: text-only `CodeableConcept`s are valid now and can be upgraded to SNOMED/RxNorm codes
  later without changing structure.
- Bad: `fhir.resources` is a large dependency and its API changed between major versions
  (v7 to v8 moved to pydantic v2 semantics); we pin `>=7.1` and use R4B explicitly.
- Bad: regional profiles (US Core etc.) are not enforced; that is a later layer.
- Neutral: pushing is opt-in (`FHIR_PUSH=1`) because the default target is a public sandbox.
