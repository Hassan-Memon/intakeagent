# ADR-0003: Local-first PHI routing with redaction fallback

- Status: accepted
- Date: 2026-11-09
- Deciders: Hassan Memon

## Context and problem statement

Structured extraction benefits from an LLM, but transcripts contain protected health
information and personal data. US HIPAA, EU/UK GDPR, UAE health data residency and KSA PDPL
transfer rules all penalise sending that data to third parties without agreements and, in
some cases, forbid leaving the country. The system needs a default that is safe and an
escape hatch that is still defensible.

## Decision drivers

- Compliance posture for US, UK, UAE and KSA buyers (see `docs/compliance.md`).
- Free-tier constraint: local inference (Ollama) is free; so is Groq, but Groq is cloud.
- Keep one code path for extraction regardless of provider.
- Demo must work with no keys at all.

## Considered options

1. Cloud LLM only, rely on vendor agreements.
2. Local LLM only.
3. Local-first: prefer a local or OpenInfer `private` endpoint; allow a cloud endpoint only
   behind an explicit flag and only after regex redaction with local re-hydration.
4. Local-first plus Presidio NER redaction for the cloud path.

## Decision outcome

Chosen option 3, with option 4 as an optional extra. `intakeagent/llm/provider.py` resolves
the provider in this order: OpenInfer if configured (requests tagged `private` via
`extra_body` and `X-OpenInfer-Tags`), then Ollama if reachable, then Groq only if
`ALLOW_CLOUD_LLM=1`, else the rule-based extractor. `LLMExtractor` checks `choice.is_local`;
when false it calls `redaction.redact()` before the prompt and `rehydrate_record()` after the
structured response. Placeholders are typed (`[NAME_1]`, `[PHONE_1]`) and stable per value so
the model can still track co-reference.

### Consequences

- Good: the safe path is the default path; turning on cloud requires a deliberate flag.
- Good: the same `with_structured_output(schema)` call works for every provider because all
  speak the OpenAI dialect.
- Good: the OpenInfer tag gives a second product (an inference router) a clear policy hook.
- Bad: regex redaction is not de-identification. Unusual names, addresses without a street
  suffix, and free-text identifiers can leak. The compliance doc says so explicitly.
- Bad: local models are weaker extractors than frontier cloud models; quality on the local
  path depends on the hardware the customer brings.
- Mitigation: the `presidio` extra can layer NER-based detection on top of the regexes; tests
  in `tests/test_redaction.py` lock in current coverage.

## Confirmation

`tests/test_redaction.py` covers phones, emails, SSN/CNIC/Emirates ID, names, DOB, addresses
and round-trip re-hydration. `tests/test_api.py::test_health_reports_demo_mode` asserts the
default provider is local.
