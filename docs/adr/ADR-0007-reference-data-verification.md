# ADR-0007: Reference-data checks as reviewer suggestions, with offline fallbacks

- Status: accepted
- Date: 2026-11-13
- Deciders: Hassan Memon

## Context and problem statement

An extracted record can be well-formed and still be unusable or unsafe downstream. In the
clinic vertical, medications, allergies and complaints were exported as free text
(`{"text": "amoxicilin 500"}`), so an EHR cannot run interaction checks, de-duplicate the
medication list or code the visit, and staff re-key it. Nothing noticed when a patient
reported a penicillin allergy and also listed amoxicillin. In the legal vertical, a firm
should know whether the client or the other side appears on a sanctions list before it opens
a matter, and the intake already captures every party name.

Free public reference data answers both problems: the U.S. National Library of Medicine
publishes RxNorm, RxClass and ICD-10-CM search APIs, and OFAC and the UN publish their
sanctions lists. How should the agent use that data without undermining the safety model
(ADR-0004) or the local-first privacy model (ADR-0003)?

## Decision drivers

- A person stays responsible for the record. Reference data must not change it silently.
- Confidential data must not leak: no patient identifiers to NLM, no client names to a
  screening service.
- The demo and the tests run offline (`DEMO_MODE`), and a third-party outage must not block
  review.
- A missing data source must be visible. "No list loaded" must never look like "no match".
- The model must not invent codes.

## Considered options

1. Let the LLM extractor emit RxNorm and ICD-10 codes directly.
2. Auto-apply the best code and block approval on any flag.
3. Add a `verify` graph node that produces suggestions and flags. The reviewer accepts codes,
   and approval with flags needs an explicit, audited acknowledgement.

## Decision outcome

Chosen option 3.

- `verify` runs after `detect_missing` and before `await_approval`, and its result rides in
  the interrupt payload. `POST /sessions/{id}/verify` re-runs it on the reviewer's edited
  record. It is read-only: it never writes to the record.
- Clinical (`intakeagent/verify/clinical.py`, `terminology.py`): medications resolve to
  RxNorm with ingredients and DailyMed pharmacologic classes. Allergies are cross-checked
  three ways: same ingredient, a class named by the allergy word ("penicillin", "sulfa"), or
  a class shared with the resolved allergen. The chief complaint and conditions get ICD-10-CM
  suggestions. Only drug names and a keyword form of the complaint are sent to NLM.
- Legal (`intakeagent/verify/sanctions.py`): OFAC SDN, OFAC Consolidated and the UN
  Consolidated List are downloaded into one JSON file and matched **locally** with
  normalised, token-based fuzzy scoring.
- Accepted codes live in `PatientIntake.codes`, keyed by the exact text they code, so editing
  a medication name drops its stale code. The LLM extractor discards any `codes` it
  produces.
- The FHIR exporter writes accepted codes as `coding` next to the patient's own `text`. The
  Clio exporter re-screens at export and adds a screening summary to the matter.
- Approving with flags requires the reviewer to tick an acknowledgement, and the flag ids are
  written to the `record.approved` audit event.
- Offline: a snapshot generated from the live NLM APIs is bundled
  (`verify/data/terminology_snapshot.json`). DEMO_MODE uses it, and the live client falls
  back to it on any network error. DEMO_MODE screens against a fictional list. Production
  without a downloaded list reports `unavailable`.

### Consequences

- Good: exports become interoperable (RxNorm, ICD-10-CM) without the model guessing codes,
  and the reviewer sees why each suggestion was made.
- Good: the confidentiality boundary is unchanged for legal data, and narrowed but explicit
  for clinical data (drug names and complaint keywords to NLM, documented in compliance.md).
- Good: the demo shows a real catch, a penicillin allergy plus amoxicillin, with no network.
- Bad: finishing an intake with live NLM takes a few seconds (about 5 s for the demo patient),
  and NLM's limit of 20 requests per second caps throughput per server IP. Responses are
  cached in-process.
- Bad: fuzzy sanctions matching produces false positives on common names. That is the
  accepted direction of error for screening, and the reviewer resolves it.
- Bad: the snapshot ages. It covers common drugs and complaints only, and must be regenerated
  (`python -m intakeagent.verify.terminology snapshot`), which also refreshes the browser
  demo copy.
- Neutral: this is reference lookup, not clinical decision support or legal advice. Nothing is
  blocked except by the reviewer's own acknowledgement.

## Confirmation

`tests/test_verify.py` covers the snapshot client, the live client against canned NLM
responses (`httpx.MockTransport`), fallback on outage, allergy rules, OFAC and UN parsing,
scoring and the `unavailable` state, and checks that the frontend data copies match.
`tests/test_api.py` covers the verification in the interrupt payload, re-verifying an edit,
audited acknowledgements, codes in the FHIR bundle and screening in the Clio export.
