# Security policy

IntakeAgent processes health and legal information, which is exactly the kind of data that
must be handled carefully. This document explains how to report a problem and what the MVP
does and does not protect.

## Reporting a vulnerability

Please do not open a public GitHub issue for security problems. Use GitHub's private
vulnerability reporting on this repository ("Security" tab, "Report a vulnerability").
You should get an acknowledgement within 72 hours.

Please include: affected component (backend, frontend, exporter, docs), reproduction steps,
and the impact you believe it has. Proof-of-concept data must be synthetic. Never send real
patient or client information.

## Supported versions

Only the `main` branch is supported. This is an MVP; there are no release branches yet.

## Security model in one paragraph

Audio and transcripts stay on the backend you run. Structured extraction runs against a
local model by default (Ollama or an OpenInfer box tagged "private"). If you opt in to a
cloud LLM (`ALLOW_CLOUD_LLM=1`) the transcript passes through `intakeagent.redaction`
first, which replaces names, phone numbers, emails, national IDs, dates of birth and
addresses with placeholders that are re-hydrated locally. Nothing is exported to FHIR or
Clio until a human approves the record. See `docs/compliance.md` for the full mapping to
HIPAA technical safeguards and the explicit "does not yet" list.

## Known limitations (MVP)

- No authentication or authorisation on the API. Run it behind your own identity layer.
- Database encryption at rest is left to the database provider (Neon, RDS, your disk).
- Audit log is an application table, not a tamper-evident store.
- Regex redaction is a safety net, not a guarantee. Keep the LLM local for real PHI.
- The public HAPI FHIR sandbox is for synthetic data only. `FHIR_PUSH` defaults to off.

## Dependencies

Dependabot style updates are welcome. Pin versions in `backend/uv.lock` and
`frontend/package-lock.json`, and run the full CI before merging.
