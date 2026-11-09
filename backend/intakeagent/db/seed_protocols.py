"""Seed intake protocol snippets.

These are short, generic coordinator notes. A real deployment replaces them with the clinic's
or firm's own intake protocol documents (any text; the store chunks nothing, one row per hint).
"""

from __future__ import annotations

from intakeagent.db.models import ProtocolDoc
from intakeagent.db.rag import ProtocolStore

SEED: list[tuple[str, str, str, str]] = [
    # (vertical, field_name, title, content)
    (
        "healthcare",
        "full_name",
        "Identity verification",
        "Ask for the full legal name as it appears on the insurance card. Confirm spelling.",
    ),
    (
        "healthcare",
        "date_of_birth",
        "Two identifiers",
        "Date of birth is the second patient identifier. Ask for day, month and year.",
    ),
    (
        "healthcare",
        "chief_complaint",
        "Chief complaint",
        "Capture the complaint in the patient's own words before asking clarifying questions.",
    ),
    (
        "healthcare",
        "symptom_onset",
        "Onset and duration",
        "Ask when symptoms started and whether they are getting better, worse or staying the same.",
    ),
    (
        "healthcare",
        "medications",
        "Medication reconciliation",
        "For each medication confirm the name, dose and how often it is taken, including "
        "over the counter drugs and supplements.",
    ),
    (
        "healthcare",
        "allergies",
        "Allergy check",
        "Ask about medication, food and latex allergies and the reaction experienced. "
        "Record no known allergies explicitly.",
    ),
    (
        "healthcare",
        "insurance_payer",
        "Insurance",
        "Ask for the insurance provider and member ID on the card. Note if self-pay.",
    ),
    (
        "legal",
        "client_name",
        "Client identity",
        "Record the client's full legal name and any former names for the conflict check.",
    ),
    (
        "legal",
        "matter_type",
        "Practice area",
        "Classify the matter into a practice area early so the right attorney reviews it.",
    ),
    (
        "legal",
        "matter_description",
        "Narrative",
        "Let the client describe events in their own words. Do not give legal advice "
        "during intake.",
    ),
    (
        "legal",
        "opposing_party",
        "Adverse parties",
        "Identify every adverse party, including companies and their known representatives.",
    ),
    (
        "legal",
        "key_dates",
        "Limitation periods",
        "Capture incident dates, contract dates and any deadlines so limitation periods can be "
        "checked immediately.",
    ),
    (
        "legal",
        "conflict_check_names",
        "Conflict check",
        "List all individuals and entities involved, with spelling confirmed, for the conflicts "
        "database search.",
    ),
]


def seed_protocols(store: ProtocolStore) -> int:
    """Insert seed docs if the store is empty. Returns rows added."""
    if store.count() > 0:
        return 0
    docs = [ProtocolDoc(vertical=v, field_name=f, title=t, content=c) for v, f, t, c in SEED]
    store.add(docs)
    return len(docs)


def hint_for(store: ProtocolStore, vertical: str, field_name: str) -> str | None:
    """Best protocol snippet for a field, used by the ask_next_question node."""
    hits = store.search(field_name.replace("_", " "), vertical, k=1)
    if not hits:
        return None
    doc, score = hits[0]
    # Prefer an exact field match when the embedding search picks a neighbour.
    if doc.field_name != field_name and score < 0.5:
        return None
    return doc.content
