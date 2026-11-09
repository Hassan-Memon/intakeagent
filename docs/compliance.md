# Compliance notes

This document maps what the IntakeAgent MVP actually does to the technical expectations of
the regimes buyers in the US, UK/EU, UAE and KSA will ask about. It is an engineering
description, not legal advice. Each deployment needs its own risk assessment, and any
production use with real patient or client data needs review by qualified counsel and a
security assessor.

## Data in scope

| Data | Where it lives | Lifetime |
| --- | --- | --- |
| Audio segments | Memory of the backend process only; passed to the STT provider; never written to disk by the app | Seconds |
| Transcript segments and merged transcript | `intake_sessions` table | Until deleted by operator |
| Structured record with evidence quotes | `intake_sessions.record`, `intake_records.record` | Until deleted by operator |
| Export payloads and responses | `intake_records.export_result` | Until deleted by operator |
| Audit trail | `audit_events` | Append-only |
| LangGraph thread state | In-process `MemorySaver` | Process lifetime |

Protected health information (PHI) and personal data appear in all of the rows above. The
database provider's encryption at rest and your network boundary are what protect them.

## HIPAA Security Rule, technical safeguards (45 CFR 164.312)

| Standard | Spec | MVP today | Gap / production plan |
| --- | --- | --- | --- |
| 164.312(a)(1) Access control | Unique user ID | Not implemented. `approved_by` is a free-text string. | Put the API behind an identity provider (OIDC); record the authenticated principal in `approved_by` and `audit_events.actor`. |
| | Emergency access | Not implemented | Operator runbook |
| | Automatic logoff | Not implemented (stateless API) | Enforce at the identity layer and in the frontend session |
| | Encryption and decryption | Delegated to the database (Neon, RDS, disk encryption) | Add application-level field encryption for `record` and `transcript` if required by risk analysis |
| 164.312(b) Audit controls | | `audit_events` records session created, transcript appended, finished, approved, exported, with timestamps. `GET /sessions/{id}/audit`. | Ship to an append-only, tamper-evident store (object lock or SIEM). Add read-access events. |
| 164.312(c)(1) Integrity | | Pydantic validation on every record write; FHIR resources validated by `fhir.resources`; evidence spans tie each value to its source text. | Row-level checksums or signed exports |
| 164.312(d) Person or entity authentication | | Not implemented | OIDC / SSO in front of REST and WebSocket (check the `Origin` header and a bearer token on upgrade) |
| 164.312(e)(1) Transmission security | | TLS is provided by the hosting layer (Vercel, Render) in the documented deploy; `docker compose` is plain HTTP for local use. | Terminate TLS in front of the backend in any real deployment; use `wss://`. |

### Minimum necessary and third parties

- **Speech-to-text.** `faster_whisper` keeps audio on the box. `groq` sends audio to Groq, which
  would require a Business Associate Agreement before real PHI is used. The `stub` sends nothing.
- **LLM.** Default routing is local (Ollama or OpenInfer with the `private` tag). A cloud
  provider is only used when `ALLOW_CLOUD_LLM=1`, and then only after `intakeagent.redaction`
  replaces names, phone numbers, emails, national IDs, dates and street addresses with
  placeholders. Regex redaction reduces exposure; it does not make the text de-identified under
  the Safe Harbor method (18 identifiers) and should not be relied on for that.
- **FHIR.** `FHIR_PUSH=1` posts to whatever `FHIR_BASE_URL` points at. The default is the
  public HAPI sandbox, which is for synthetic data only and must never receive real PHI.
- **Clio.** Live mode posts to Clio's API; Clio is the law firm's processor under its own terms.

## GDPR and UK GDPR

| Principle | How the MVP supports it | Still needed |
| --- | --- | --- |
| Lawfulness and transparency (Art. 5, 13) | The intake screen states that a person reviews every record before export | Privacy notice text, lawful basis per deployment (health data is special category: Art. 9(2)(h) typically) |
| Purpose limitation and data minimisation | Schemas define exactly which fields are captured; nothing outside the schema is persisted as structured data | Transcript retention policy; configurable redaction of the raw transcript after approval |
| Accuracy | Human review and edit before export; evidence quotes make corrections easy | |
| Storage limitation | Nothing is auto-deleted | Retention job and deletion endpoint |
| Integrity and confidentiality | See HIPAA table | Same |
| Data subject rights (Art. 15 to 22) | Records are addressable by session id and exportable as JSON | Erasure endpoint covering `intake_sessions`, `intake_records`, `audit_events` and downstream FHIR/Clio |
| International transfers (Ch. V) | Local STT and LLM avoid transfers; Groq, Gemini, OpenRouter are US-hosted | Transfer impact assessment and SCCs if a cloud provider is enabled |
| Processor terms (Art. 28) | | DPAs with hosting (Vercel, Render, Neon) and any STT/LLM vendor |

UK GDPR is materially identical for this system; the ICO's guidance on AI and data protection
adds an expectation of documented human oversight, which the mandatory approval step satisfies
in design terms.

## UAE Personal Data Protection Law (Federal Decree-Law No. 45 of 2021) and health data

- The PDPL mirrors GDPR concepts (lawful basis, minimisation, data subject rights, breach
  notification). The mapping in the GDPR table applies.
- Health data additionally falls under Federal Law No. 2 of 2019 (ICT in health fields), which
  restricts storing or transferring health information outside the UAE except where the Ministry
  permits. Practical consequence: deploy the backend, database, STT and LLM inside the UAE
  (an on-premise box or a UAE region) and keep `ALLOW_CLOUD_LLM=0` unless the vendor is in-country.
- DHA (Dubai) and DoH (Abu Dhabi) facilities have their own standards for health information
  systems; the FHIR R4 output helps with interoperability expectations but does not by itself
  satisfy those standards.
- The free-tier remote deployment in the README (Vercel, Render, Neon) is **not** suitable for
  UAE health data because of data residency; use it only for demos with synthetic data.

## KSA Personal Data Protection Law (Royal Decree M/19, in force 2023, amended 2024)

- Health data is sensitive data; processing requires a clear lawful basis and additional
  safeguards. Explicit consent is the usual route for intake.
- Cross-border transfer rules (Art. 29 and the 2024 transfer regulations) require an adequacy
  decision, appropriate safeguards, or a specific exception. Default to in-Kingdom hosting for
  the backend, database and inference, which the local-first design supports directly.
- The NDMO and SDAIA guidance expect records of processing and a data protection impact
  assessment for high-risk processing. The audit table and the schema definitions give you the
  raw material; the assessment itself is a deployment task.
- The National Platform for Health Information Exchange (NPHIES) uses FHIR R4 profiles; the
  exporter's Bundle is a starting point, but Saudi Core profiles would need to be applied.

## What the MVP does

- Keeps audio in memory and never writes it to disk.
- Defaults every outbound AI call to local infrastructure; cloud LLM is off by default and
  redacted when on.
- Validates every record against a typed schema and every FHIR resource against the R4 profile.
- Requires a human to approve before anything is exported; the graph cannot reach `export`
  without passing through the `interrupt()` in `await_approval`.
- Writes an application audit trail of session and record lifecycle events.
- Stores evidence spans so reviewers can verify each value against the transcript.
- Runs entirely offline in `DEMO_MODE` so demos never involve real data or external services.

## What the MVP does not yet do

- Authenticate users or authorise actions. The API is open; put it behind your identity layer.
- Encrypt fields at the application level or manage keys.
- Enforce retention or provide an erasure endpoint.
- Produce a tamper-evident audit log or log read access.
- Guarantee de-identification. The regex redactor is a safety net.
- Check the WebSocket `Origin` header or require a token on upgrade.
- Provide BAAs, DPAs or any contractual artefacts; those are between you and your vendors.
- Apply regional FHIR profiles (US Core, UK Core, Saudi Core).
- Sign or verify exported payloads.

## Deployment checklist for real data

1. Local or in-region STT (`faster_whisper`) and LLM (Ollama/OpenInfer). `ALLOW_CLOUD_LLM=0`.
2. `FHIR_BASE_URL` pointing at your own FHIR server; never the public sandbox.
3. TLS everywhere (`https://`, `wss://`); identity provider in front of REST and WebSocket.
4. Managed Postgres with encryption at rest, backups and network isolation; `pgvector` enabled.
5. Retention policy implemented as a scheduled job; erasure runbook covering downstream systems.
6. Audit events shipped to immutable storage.
7. Risk analysis / DPIA on file, BAAs or DPAs executed with each processor.
