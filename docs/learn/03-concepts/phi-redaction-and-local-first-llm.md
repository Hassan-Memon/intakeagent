# PHI redaction and local-first LLM

## Two layers of protection

IntakeAgent protects transcripts with placement first and redaction second. **Placement**
means the model runs where the data already is: Ollama on the same box, or an OpenInfer
endpoint the customer controls. **Redaction** is what happens when someone deliberately opts
into a cloud provider: the transcript is scrubbed before it leaves and restored after the
answer returns. Redaction is the seat belt; placement is driving carefully.

## The provider abstraction

`backend/intakeagent/llm/provider.py` returns an `LLMChoice` with `provider`, `base_url`,
`api_key`, `model` and, crucially, `is_local`. All supported providers speak the OpenAI chat
dialect, so `get_chat_model` builds one `ChatOpenAI(base_url=...)`. For OpenInfer we add
`extra_body={"tags": ["private"]}` and an `X-OpenInfer-Tags` header so its router knows this
request must stay on local hardware.

Resolution for `LLM_PROVIDER=auto`: OpenInfer if `OPENINFER_BASE_URL` is set, else Ollama if
`/api/tags` answers, else Groq if a key exists, else the stub (rules). `DEMO_MODE=1` forces
the stub. `ALLOW_CLOUD_LLM` defaults to off, so even with a Groq key the extractor refuses the
cloud path and falls back to rules unless the operator flips the flag.

## How the redactor works

`backend/intakeagent/redaction/phi.py` applies an ordered list of `(label, regex)` patterns:
email, national IDs (US SSN, Pakistan CNIC, UAE Emirates ID, KSA national ID), phone numbers,
dates in several formats, street addresses, and names introduced by phrases ("my name is",
"Mr.", "my manager Karen Blake"). Order matters: IDs run before phones so `123-45-6789` is not
half-eaten as a phone number. Each match becomes a typed placeholder such as `[NAME_1]`; the
same original always maps to the same placeholder so the model can follow co-reference. The
mapping stays in process memory.

After the model answers, `rehydrate_record` walks the structured output (dicts, lists,
strings) and swaps placeholders back. The record the reviewer sees contains real values; the
cloud provider only ever saw tokens.

## Why regex and not only NER

Regex is deterministic, fast, auditable and has no model to download. Its weaknesses are
recall on unusual names and addresses without a recognisable suffix. Microsoft Presidio adds
NER-based recognisers; the `presidio` extra is the hook for it. Neither approach makes text
"de-identified" under HIPAA's Safe Harbor method, which lists 18 identifier categories and
requires removing all of them. That is why `docs/compliance.md` calls redaction a safety net
and recommends local inference for real PHI.

## Structured output with placeholders

The system prompt in `graph/extractors.py` tells the model that tokens like `[NAME_1]` are
placeholders to copy verbatim. Models handle this well because the schema asks for the value
and the quote; both come back containing the placeholder, and both are re-hydrated.

## Testing the boundary

`tests/test_redaction.py` asserts each category disappears, clinical content survives
("allergic to penicillin" is not PHI), repeated names share a placeholder, and round-trip
re-hydration restores nested values. When you add a pattern, add a test with a synthetic
example; never paste real data into tests.

## Operational rules this implies

- Default to `ALLOW_CLOUD_LLM=0`; turn it on per deployment with a documented reason.
- Keep STT local too: redaction protects text, not audio.
- Log the redaction count, never the mapping.
- Treat the transcript column in Postgres as PHI regardless of what the LLM saw.
