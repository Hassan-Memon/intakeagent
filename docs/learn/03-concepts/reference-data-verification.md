# Reference-data verification

## What it does and what it does not

Between "the patient finished talking" and "a person approves", the graph runs a `verify` node
(`backend/intakeagent/verify/`). It checks the record against public reference data and
returns suggestions and flags for the review screen:

- **Healthcare:** each medication is coded to RxNorm, each medication is cross-checked against
  the reported allergies, and the chief complaint and conditions get ICD-10-CM suggestions.
- **Legal:** the client, the opposing party and every conflict-check name are screened against
  OFAC and UN sanctions lists.

Nothing here edits the record or blocks approval. A code reaches the export only if the
reviewer accepts it, and a flag only has to be acknowledged. This is reference lookup to speed
up review, not clinical decision support or legal advice.

## RxNorm in five terms

RxNorm (U.S. National Library of Medicine) gives every drug concept an **rxcui**. Each concept
has a **term type (TTY)**: `IN` is an ingredient (amoxicillin, 723), `BN` a brand (Augmentin,
151392), `SCD` a clinical drug (amoxicillin 500 MG, 317616). RxNav's `approximateTerm` turns
messy speech ("amoxicilin 500") into ranked candidates, `related?tty=IN` goes from a brand or
clinical drug to its ingredients, and `properties` returns the current name and TTY.

Candidates come from several vocabularies. The rank-1 candidate for "Bactrim DS" is a retired
MMSL concept with no current properties, so `NlmTerminologyClient.lookup_drug`
(`verify/terminology.py`) sorts RXNORM-sourced candidates first and takes the first one RxNorm
still knows:

```python
ordered = sorted(candidates,
                 key=lambda c: (c.get("source") != "RXNORM", int(c.get("rank", 99))))
for cand in ordered:
    props = self._get(f"{self.RXNAV}/rxcui/{cand['rxcui']}/properties.json")
    if (props.get("properties") or {}).get("name"):
        ...
```

## RxClass: "is a" versus "contraindicated with"

Allergy checks need drug classes. RxClass returns relations from several sources, and they
look alike. DailyMed's `has_epc` (established pharmacologic class, "Penicillin-class
Antibacterial") and `has_chemical_structure` ("Penicillins") describe what a drug *is*.
MED-RT's `ci_chemclass` means the drug is *contraindicated with* that class, which is why an
early snapshot listed "Disulfiram" as a class of Augmentin. `CLASS_RELAS` keeps only the two
DailyMed relations.

## Allergy cross-check rules

`_allergy_flags` in `verify/clinical.py` flags a medication against an allergy when:

1. **Same ingredient** (severity `high`): Advil contains ibuprofen; the patient is allergic to
   ibuprofen.
2. **Class word** (`warning`): the allergy names a class ("penicillin", "sulfa drugs",
   "NSAIDs", mapped in `ALLERGEN_CLASS_TERMS`) and a class name of the medication contains it.
3. **Shared class** (`warning`): the allergen resolves to a drug that shares a class with the
   medication (allergic to naproxen, taking ibuprofen).

Two guards came from testing against live data. Class allergens are never looked up as
products, because RxNorm's nearest string to "sulfa drugs" is a product called "Supra Sulfa".
An allergen match with confidence below 0.6 is shown but never drives a flag. Food and
environmental allergens (`NON_DRUG_ALLERGENS`) are skipped.

## ICD-10-CM suggestions

NLM Clinical Tables searches ICD-10-CM by requiring every query word to prefix some word of
the code's name. Patient words rarely match: "sharp pain in my lower right side" returns
nothing. `complaint_query` rewrites lay terms and drops filler:

```python
complaint_query("sharp pain in my lower right side")  # "pain right lower quadrant" -> R10.31
```

If the full query misses, `_icd_suggestions` tries shorter word windows, capped at six
searches. The reviewer always picks the code, or none; ICD codes are never pre-selected.

## Codes in FHIR, keyed by text

A FHIR `CodeableConcept` holds the original words in `text` and standard codes in `coding`.
Accepted codes live in `PatientIntake.codes` (`ReviewerCodes`), one map per field, keyed by
the exact text coded:

```json
{"medications": {"amoxicillin": {"system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                 "code": "723", "display": "amoxicillin"}}}
```

`_concept` in `exporters/fhir.py` adds a coding only if the key still matches. If the reviewer
renames a medication after accepting its code, the stale code is not exported against the new
words. Extractors never set `codes`; `LLMExtractor` drops the key so a model cannot invent one.

## Live, snapshot, fallback

`OfflineTerminologyClient` answers from `verify/data/terminology_snapshot.json`, generated
from the live APIs by `python -m intakeagent.verify.terminology snapshot` (34 drugs, 118
ICD-10-CM codes). DEMO_MODE and tests use it. `FallbackTerminologyClient` calls NLM and drops
to the snapshot on a network error, reporting `mode: "offline"` in the result's `sources`.
The browser demo ships the same JSON (`frontend/lib/demo/data/terminology.json`, used by
`lib/demo/verify.ts`); `test_frontend_snapshot_matches_backend` fails if the copies differ.

## Sanctions screening, locally

The lists are public; the names in an intake are confidential. So `verify/sanctions.py`
downloads OFAC SDN and OFAC Consolidated (CSV, with alias files) and the UN Consolidated List
(XML) into one JSON file, and every comparison runs in process. No name is sent anywhere.

Matching:

- `normalize_name` folds case and accents, removes punctuation and drops legal suffixes
  (LLC, Ltd, FZE...).
- `name_score` measures token coverage both ways, with typo tolerance per token:
  `0.7 * query_coverage + 0.3 * candidate_coverage`. The query side weighs more because every
  word the client said should be accounted for; a list entry may carry extra given names.
- At 0.85 or above a result is a `possible_match`, at 0.97 a `strong_match`. A one-word query
  ("Blake") only counts if it is a strong match.
- **Blocking:** only entries sharing a 3-letter token prefix with at least two query tokens
  are scored. On the real lists (about 21,000 entries) this took ten names from 3.9 s to
  0.16 s with identical results.

With no list loaded, the result is `status: "unavailable"` and the UI says so. Never a silent
"clear". DEMO_MODE uses a short fictional list in which "Northwind Logistix Trading FZE"
near-matches the demo's opposing party, so the demo shows a hit without naming anyone real.

## Exercises

1. Add "Keflex" to a test patient allergic to "cephalosporins" and predict which rule fires.
   Run it through `verify_patient` with `OfflineTerminologyClient`.
2. Add a synonym to `COMPLAINT_SYNONYMS` for "pins and needles" and find the ICD-10 code it
   should reach. Mirror it in `frontend/lib/demo/verify.ts`.
3. Run `python -m intakeagent.verify.sanctions screen "Mohammed Ahmed"` against a refreshed
   list. Why are common names noisy, and what extra field (date of birth) would you compare?
4. Remove the blocking step in `SanctionsList.search` and time `screen_names` on the real list.
