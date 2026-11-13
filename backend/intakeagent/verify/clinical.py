"""Clinical checks on a PatientIntake before review.

Three things, all *suggestions* for the reviewer, never automatic edits:

1. **Medication coding.** Each spoken medication is resolved to an RxNorm concept with its
   active ingredients and pharmacologic classes.
2. **Allergy cross-check.** A medication is flagged when it *is* a stated allergen (same
   ingredient) or belongs to a class the allergen names, e.g. "allergic to penicillin" plus
   "amoxicillin" (Penicillin-class Antibacterial). The flag says why, so the reviewer can judge.
3. **ICD-10-CM suggestions.** The chief complaint and reported conditions are turned into a
   short keyword query ("sharp pain in my lower right side" -> "pain right lower quadrant")
   and searched against ICD-10-CM. The reviewer picks one or none.

This is reference-data lookup to speed up record review. It is not clinical decision support:
nothing is blocked, nothing is changed without a person, and the record says what was checked.
"""

from __future__ import annotations

import re
from typing import Any

from intakeagent.schemas import PatientIntake
from intakeagent.verify.terminology import (
    Coding,
    DrugInfo,
    TerminologyClient,
    TerminologyUnavailable,
    normalize_term,
    similarity,
)

# Allergy words patients use for a whole class, mapped to words found in RxClass class names.
ALLERGEN_CLASS_TERMS: dict[str, list[str]] = {
    "penicillin": ["penicillin"],
    "penicillins": ["penicillin"],
    "sulfa": ["sulfonamide"],
    "sulfa drugs": ["sulfonamide"],
    "sulfonamides": ["sulfonamide"],
    "nsaid": ["nonsteroidal anti-inflammatory"],
    "nsaids": ["nonsteroidal anti-inflammatory"],
    "anti inflammatories": ["nonsteroidal anti-inflammatory"],
    "cephalosporins": ["cephalosporin"],
    "opioids": ["opioid"],
    "opiates": ["opioid"],
    "statins": ["hmg-coa reductase"],
    "ace inhibitors": ["angiotensin converting enzyme"],
    "macrolides": ["macrolide"],
    "tetracyclines": ["tetracycline"],
    "quinolones": ["quinolone"],
    "fluoroquinolones": ["quinolone"],
}

NON_DRUG_ALLERGENS = {
    "latex", "peanut", "peanuts", "tree nuts", "shellfish", "eggs", "egg", "milk", "dairy",
    "soy", "wheat", "gluten", "bees", "bee stings", "pollen", "dust", "cats", "dogs",
}  # fmt: skip

# Everyday words for the same anatomy or symptom, rewritten to ICD-10-CM vocabulary.
COMPLAINT_SYNONYMS: list[tuple[str, str]] = [
    (r"\b(?:lower right|right lower)\s+(?:side|abdomen|belly|stomach|tummy)\b",
     "right lower quadrant"),
    (r"\b(?:lower left|left lower)\s+(?:side|abdomen|belly|stomach|tummy)\b",
     "left lower quadrant"),
    (r"\b(?:upper right|right upper)\s+(?:side|abdomen|belly|stomach|tummy)\b",
     "right upper quadrant"),
    (r"\b(?:upper left|left upper)\s+(?:side|abdomen|belly|stomach|tummy)\b",
     "left upper quadrant"),
    (r"\b(?:stomach|belly|tummy)\s*(?:ache|pain)s?\b", "abdominal pain"),
    (r"\b(?:stomach|belly|tummy)\b", "abdominal"),
    (r"\bthrowing up\b|\bbeing sick\b", "vomiting"),
    (r"\bfeeling sick\b|\bqueasy\b", "nausea"),
    (r"\bshort(?:ness)? of breath\b|\btrouble breathing\b|\bcan'?t breathe\b",
     "shortness breath"),
    (r"\bhead\s*aches?\b|\bmy head hurts\b", "headache"),
    (r"\bsore throat\b", "pharyngitis"),
    (r"\bear\s*ache\b", "otalgia"),
    (r"\bhigh blood pressure\b", "essential hypertension"),
    (r"\bcan'?t sleep\b|\btrouble sleeping\b", "insomnia"),
    (r"\b(?:lower|low) back\b", "low back"),
    (r"\bdiabetic\b", "diabetes"),
    (r"\bsugar\b", "diabetes"),
]  # fmt: skip

STOPWORDS = {
    "a", "an", "the", "i", "i've", "ive", "my", "me", "have", "had", "has", "been", "having",
    "in", "on", "of", "at", "to", "for", "with", "and", "or", "some", "really", "very", "bad",
    "sharp", "dull", "terrible", "awful", "little", "bit", "kind", "sort", "since", "it", "its",
    "is", "this", "that", "feel", "feeling", "got", "getting", "keep", "keeps", "side", "area",
    "constant", "severe", "mild", "slight", "sudden", "lot", "pretty", "quite", "like", "around",
}  # fmt: skip


def complaint_query(text: str) -> str:
    """Turn patient wording into a short ICD-10-CM search query."""
    s = text.lower()
    for pattern, repl in COMPLAINT_SYNONYMS:
        s = re.sub(pattern, repl, s)
    words = [w for w in re.findall(r"[a-z0-9']+", s) if w not in STOPWORDS]
    return " ".join(words)


def _icd_suggestions(client: TerminologyClient, text: str, limit: int = 5) -> dict[str, Any]:
    """Search with the full query, then progressively shorter windows until something hits."""
    query = complaint_query(text)
    words = query.split()
    tried: list[str] = []
    for size in range(len(words), 0, -1):
        for start in range(0, len(words) - size + 1):
            q = " ".join(words[start : start + size])
            if q in tried:
                continue
            tried.append(q)
            hits = client.search_icd10(q, limit)
            if hits:
                return {
                    "input": text,
                    "query": q,
                    "suggestions": [h.model_dump() for h in hits],
                    "status": "matched",
                }
            if len(tried) >= 6:  # keep the call count small
                return {"input": text, "query": query, "suggestions": [], "status": "no_match"}
    return {"input": text, "query": query, "suggestions": [], "status": "no_match"}


def _strip_dose(name: str) -> str:
    return re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|milligrams?|mcg|micrograms?|ml|units?)\b", "", name)


def _drug_entry(info: DrugInfo | None, spoken: str) -> dict[str, Any]:
    if info is None:
        return {"input": spoken, "status": "no_match", "match": None}
    names = [info.name, *(i.display for i in info.ingredients)]
    confidence = max(similarity(_strip_dose(spoken), n) for n in names)
    if any(normalize_term(n) in normalize_term(spoken) for n in names):
        confidence = max(confidence, 0.95)
    return {
        "input": spoken,
        "status": "matched",
        "match": info.coding.model_dump(),
        "ingredients": [i.model_dump() for i in info.ingredients],
        "classes": [c.name for c in info.classes],
        "confidence": round(confidence, 2),
    }


def _allergy_flags(
    allergen: str, allergen_info: DrugInfo | None, med_name: str, med: DrugInfo
) -> dict[str, Any] | None:
    """Return a flag when ``med`` matches ``allergen`` by ingredient or class, else None."""
    a_norm = normalize_term(allergen)
    med_ingredients = {i.code: i.display for i in med.ingredients}
    reason = None
    kind = "allergy_class"

    # Same ingredient (allergen resolved to RxNorm, or the words match an ingredient name).
    if allergen_info:
        shared = set(med_ingredients) & {i.code for i in allergen_info.ingredients}
        if shared:
            kind = "allergy_ingredient"
            reason = f"{med_name} contains {med_ingredients[shared.pop()]}"
    if reason is None:
        for display in med_ingredients.values():
            if normalize_term(display) == a_norm:
                kind = "allergy_ingredient"
                reason = f"{med_name} contains {display}"
                break

    # Class named by the allergy word ("penicillin" -> "Penicillin-class Antibacterial").
    if reason is None:
        terms = ALLERGEN_CLASS_TERMS.get(a_norm, [a_norm.rstrip("s")])
        for cls in med.classes:
            if any(t and t in cls.name.lower() for t in terms):
                reason = f"{med_name} is in the class “{cls.name}”"
                break

    # Class shared with the resolved allergen (e.g. allergic to naproxen, taking ibuprofen).
    if reason is None and allergen_info:
        a_classes = {c.id: c.name for c in allergen_info.classes}
        for cls in med.classes:
            if cls.id in a_classes:
                reason = f"{med_name} and {allergen} share the class “{cls.name}”"
                break

    if reason is None:
        return None
    return {
        "id": f"{kind}:{a_norm}:{normalize_term(med_name)}",
        "kind": kind,
        "severity": "high" if kind == "allergy_ingredient" else "warning",
        "title": f"{med_name} may conflict with the reported {allergen} allergy",
        "detail": f"{reason} (RxNorm/RxClass). Confirm with the patient or clinician before "
        "approving; this is a reference check, not a clinical judgement.",
        "fields": ["medications", "allergies"],
    }


def _field_items(field: Any, attr: str) -> list[str]:
    out: list[str] = []
    for item in field.value or []:
        value = item.get(attr) if isinstance(item, dict) else getattr(item, attr, None)
        if value:
            out.append(str(value))
    return out


def verify_patient(record: PatientIntake, client: TerminologyClient) -> dict[str, Any]:
    errors: list[str] = []
    medications: list[dict[str, Any]] = []
    med_infos: list[tuple[str, DrugInfo]] = []

    for name in _field_items(record.medications, "name"):
        if name.lower().startswith("none"):
            continue
        try:
            info = client.lookup_drug(_strip_dose(name))
            bare = re.sub(r"\s+", " ", re.sub(r"\b\d+(?:\.\d+)?\b", "", _strip_dose(name)))
            if info is None and bare.strip() != _strip_dose(name).strip():
                info = client.lookup_drug(bare)  # "Motrin 400": a strength without a unit
        except TerminologyUnavailable as exc:
            errors.append(str(exc))
            medications.append({"input": name, "status": "error", "match": None})
            continue
        medications.append(_drug_entry(info, name))
        if info:
            med_infos.append((name, info))

    allergies: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    for substance in _field_items(record.allergies, "substance"):
        a_norm = normalize_term(substance)
        if a_norm.startswith("no known") or a_norm.startswith("none"):
            continue
        if a_norm in NON_DRUG_ALLERGENS:
            allergies.append({"input": substance, "status": "not_a_drug", "match": None})
            continue
        info: DrugInfo | None = None
        if a_norm in ALLERGEN_CLASS_TERMS:
            # "Sulfa drugs" is a class, not a product: never code it as one (RxNorm's nearest
            # string match for it is an unrelated product). Match medications by class instead.
            allergies.append(
                {
                    "input": substance,
                    "status": "drug_class",
                    "match": None,
                    "classes": ALLERGEN_CLASS_TERMS[a_norm],
                }
            )
        else:
            try:
                info = client.lookup_drug(substance)
            except TerminologyUnavailable as exc:
                errors.append(str(exc))
            entry = _drug_entry(info, substance)
            allergies.append(entry)
            if entry.get("confidence", 0) < 0.6:
                info = None  # a weak string match must not drive allergy flags
        for med_name, med_info in med_infos:
            if flag := _allergy_flags(substance, info, med_name, med_info):
                flags.append(flag)

    chief: dict[str, Any] | None = None
    conditions: list[dict[str, Any]] = []
    try:
        if record.chief_complaint.value:
            chief = _icd_suggestions(client, record.chief_complaint.value)
        for cond in record.conditions.value or []:
            conditions.append(_icd_suggestions(client, str(cond)))
    except TerminologyUnavailable as exc:
        errors.append(str(exc))

    return {
        "medications": medications,
        "allergies": allergies,
        "chief_complaint": chief,
        "conditions": conditions,
        "flags": flags,
        "errors": errors,
    }


__all__ = ["Coding", "complaint_query", "verify_patient"]
