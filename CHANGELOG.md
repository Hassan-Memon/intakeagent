# Changelog

All notable changes to IntakeAgent are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Reference checks before review** (`backend/intakeagent/verify/`, ADR-0007). A new `verify`
  graph node runs between `detect_missing` and the approval interrupt, and
  `POST /sessions/{id}/verify` re-runs it on the reviewer's edited record.
  - Medications and allergies are resolved to RxNorm with ingredients and DailyMed
    pharmacologic classes. A medication is flagged when it shares an ingredient with a reported
    allergen, belongs to a class the allergy names ("penicillin", "sulfa", "NSAIDs"), or
    shares a class with it.
  - The chief complaint and conditions get ICD-10-CM suggestions. Lay wording is rewritten
    first ("lower right side" becomes "right lower quadrant").
  - Data comes from the U.S. National Library of Medicine's free RxNav, RxClass and Clinical
    Tables APIs, with a bundled snapshot generated from them
    (`python -m intakeagent.verify.terminology snapshot`) for demo mode, tests and outages.
  - Legal intakes screen the client, opposing party and conflict-check names against OFAC SDN,
    OFAC Consolidated and the UN Consolidated List, downloaded with
    `python -m intakeagent.verify.sanctions refresh` and matched locally with fuzzy,
    token-based scoring.
- `PatientIntake.codes`: RxNorm and ICD-10-CM codes the reviewer accepted, keyed by the text
  they code. The FHIR exporter adds them as `coding` next to the patient's words.
- The Clio export re-screens at export time and records the result on the matter description
  and in `sanctions_screening`.
- `acknowledged_flags` on approve, written to the `record.approved` audit event, plus a
  `record.verified` audit event for every check.
- Review screen: a "Reference checks" panel with flags, code suggestions to tick or pick,
  sanctions results and a re-run button. Approving past a flag needs an explicit
  acknowledgement.
- The browser demo runs the same checks in `lib/demo/verify.ts` on the same snapshot and a
  fictional sanctions list, so nothing leaves the page. A backend test keeps the data copies
  identical.
- Settings `TERMINOLOGY_PROVIDER` (`auto`, `nlm` or `offline`) and `SANCTIONS_LIST_PATH`;
  `/health` reports both.
- 29 new tests (69 in total), including the live NLM client against canned responses.

### Changed
- The sample patient also takes amoxicillin, so the demo shows the penicillin-allergy flag.
- The language-model extractor discards any `codes` it returns: codes come only from a
  reviewer accepting reference data.

## [0.1.0] - 2026-11-10

First public release. This repository previously held a 2020 Django weather app. Its history
was replaced with a clean branch so an old API key would not be published, and the repository
was rebuilt as IntakeAgent.

### Added
- **Intake schemas:** `PatientIntake` and `LegalIntake`. Each field records whether it is
  required, the question that asks for it, and the transcript evidence it came from.
- **Intake agent (LangGraph):** merges the transcript, extracts fields with a language model or
  with deterministic rules in demo mode, finds the next missing field, asks for it, then pauses
  for human approval before export.
- **Speech to text:** a stub for demo mode, Groq Whisper large v3 on the free API, and
  faster-whisper locally as an optional extra.
- **Privacy:** regex redaction of names, phone numbers, emails, ID numbers, dates of birth and
  addresses before any cloud model call. Cloud models are off by default, and the local model
  is called with the OpenInfer `private` tag.
- **Exporters:** a FHIR R4 transaction Bundle built with `fhir.resources` (Patient, Encounter,
  Condition, AllergyIntolerance, MedicationStatement and Coverage), with an optional push to the
  public HAPI FHIR sandbox. A Clio exporter produces Contact and Matter payloads in the Clio v4
  shape, with an OAuth2 client and a mock mode.
- **Backend (FastAPI):** REST endpoints for sessions, approval, export and records, and a
  WebSocket that streams audio in and transcript and questions out. Persistence uses SQLModel
  on Postgres, with pgvector retrieval over intake protocols and SQLite fallbacks.
- **Frontend (Next.js 15):** choose a vertical, a live intake screen with microphone, level
  meter, transcript and question panel, a review screen with editable fields and evidence, and
  a records list.
- **Demo mode:** with `NEXT_PUBLIC_DEMO_MODE=1` the frontend uses a TypeScript port of the rule
  extractor, question picker and exporters, checked against the real backend with no
  differences. Sample conversations use fictional people. Deployed to Cloudflare Workers through
  OpenNext at https://intakeagent.hassan-memon.workers.dev.
- **Documentation:** a WebSocket protocol spec, a compliance mapping for HIPAA technical
  safeguards, GDPR and UK GDPR, UAE PDPL and KSA PDPL with a list of what is not done yet, six
  architecture decision records, positioning, and a teaching track in `docs/learn/`.
- **Tests and CI:** 40 offline backend tests, frontend lint, type check and build, and Compose
  validation in GitHub Actions.

### Fixed
- The browser now calls the backend on `127.0.0.1`, which avoids a failure when `localhost`
  resolves to IPv6, and CORS allows both loopback origins.
- The required-fields checklist starts with every field missing instead of every field ticked.
- The review screen button "Add allergie" now reads "Add allergy".

[0.1.0]: https://github.com/Hassan-Memon/intakeagent/commits/main
