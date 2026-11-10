// Port of backend/intakeagent/graph/questions.py plus the protocol hints the backend's
// DEMO_MODE retrieval (hashing embeddings over db/seed_protocols.py) returns for each field.

import type { FieldSpec, Vertical } from "../types";

export const OPENERS: Record<Vertical, string> = {
  healthcare:
    "Hello, I'm the intake assistant. I'll ask a few questions before you see the clinician. " +
    "You can speak naturally.",
  legal:
    "Hello, I'm the intake assistant for the firm. I'll gather some details so a lawyer can " +
    "review your matter. You can speak naturally.",
};

export const CLOSERS: Record<Vertical, string> = {
  healthcare:
    "Thank you. I have everything I need for now. A member of staff will review your details " +
    "before they go into your chart.",
  legal:
    "Thank you. I have what I need for a conflict check. A member of the team will review your " +
    "details before a matter is opened.",
};

// What `hint_for(store, vertical, field)` returns in DEMO_MODE. Fields without an entry get no
// hint (either no seed snippet or the nearest snippet scores too low). Captured from the real
// backend so question text matches it word for word.
const HINTS: Record<Vertical, Record<string, string>> = {
  healthcare: {
    full_name:
      "Ask for the full legal name as it appears on the insurance card. Confirm spelling.",
    date_of_birth:
      "Date of birth is the second patient identifier. Ask for day, month and year.",
    chief_complaint:
      "Capture the complaint in the patient's own words before asking clarifying questions.",
    allergies:
      "Ask about medication, food and latex allergies and the reaction experienced. " +
      "Record no known allergies explicitly.",
    insurance_payer:
      "Ask for the insurance provider and member ID on the card. Note if self-pay.",
  },
  legal: {
    client_name:
      "Record the client's full legal name and any former names for the conflict check.",
    matter_type:
      "Classify the matter into a practice area early so the right attorney reviews it.",
    opposing_party:
      "Identify every adverse party, including companies and their known representatives.",
    key_dates:
      "Capture incident dates, contract dates and any deadlines so limitation periods can be " +
      "checked immediately.",
    conflict_check_names:
      "Record the client's full legal name and any former names for the conflict check.",
  },
};

export function hintFor(vertical: Vertical, field: string): string | null {
  return HINTS[vertical][field] ?? null;
}

/** next_question(): first missing field in declaration order, softened on a repeat. */
export function nextQuestion(
  specs: FieldSpec[],
  missing: string[],
  asked: string[],
  hint: string | null,
): [string | null, string | null] {
  const byName = new Map(specs.map((s) => [s.name, s]));
  for (const name of missing) {
    const spec = byName.get(name);
    if (!spec) continue;
    let question = spec.question;
    if (asked.length && asked[asked.length - 1] === question) {
      question = `Sorry, I did not catch that. ${question}`;
    }
    if (hint) question = `${question} (${hint})`;
    return [question, name];
  }
  return [null, null];
}
