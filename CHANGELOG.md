# Changelog

All notable changes to IntakeAgent are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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
