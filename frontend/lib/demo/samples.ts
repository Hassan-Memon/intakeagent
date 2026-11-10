// Scripted sample conversations for the in-browser demo. Every name, number, address and
// company here is invented: 555-01xx numbers and example.com addresses are reserved for
// fiction, and the people are named "Example", "Sample" and "Placeholder" on purpose.
//
// Each line lists the fields it answers. The player picks the line that answers the agent's
// current question first, so the conversation reads naturally, then plays any leftovers.

import type { Vertical } from "../types";

export interface SampleLine {
  text: string;
  answers: string[];
}

export const SAMPLE_LABEL: Record<Vertical, string> = {
  healthcare: "sample patient",
  legal: "sample client",
};

export const SAMPLES: Record<Vertical, SampleLine[]> = {
  healthcare: [
    {
      text: "Hi, my name is Jordan Example and I was born on March 4th, 1986.",
      answers: ["full_name", "date_of_birth"],
    },
    {
      text: "Sure, it's 415-555-0134. I live at 220 Maple Street, Springfield.",
      answers: ["phone", "address"],
    },
    {
      text:
        "I've had a sharp pain in my lower right side since Tuesday evening, " +
        "it's about a six out of ten.",
      answers: ["chief_complaint", "symptom_onset", "symptom_severity"],
    },
    {
      text: "I take metformin 500 milligrams twice a day and lisinopril 10 milligrams every morning.",
      answers: ["medications"],
    },
    {
      text: "I'm allergic to penicillin, it gives me hives. I was diagnosed with type 2 diabetes in 2019.",
      answers: ["allergies", "conditions"],
    },
    {
      text: "My insurance is Acme Demo Health, member ID DEMO-88213.",
      answers: ["insurance_payer", "insurance_member_id"],
    },
  ],
  legal: [
    {
      text: "My name is Casey Sample, you can reach me at 212-555-0188 or casey.sample@example.com.",
      answers: ["client_name", "phone", "email"],
    },
    {
      text:
        "This is an employment matter. I was fired from Northwind Logistics on June 12th, 2025 " +
        "after I reported safety violations to HR.",
      answers: ["matter_type", "matter_description", "opposing_party", "key_dates"],
    },
    {
      text: "The other party is Northwind Logistics and my manager Taylor Placeholder.",
      answers: ["conflict_check_names"],
    },
    {
      text:
        "I received a severance letter on June 20th, 2025 with a deadline to sign by " +
        "July 15th, 2025.",
      answers: ["urgency"],
    },
    {
      text: "It happened in Newark, New Jersey. The deadline is what makes this urgent.",
      answers: ["jurisdiction"],
    },
  ],
};

/** Index of the next line to play given the field the agent is asking about. */
export function pickSampleLine(
  vertical: Vertical,
  used: number[],
  field: string | null,
): number | null {
  const lines = SAMPLES[vertical];
  const unused = lines.map((_, i) => i).filter((i) => !used.includes(i));
  if (unused.length === 0) return null;
  if (field) {
    const match = unused.find((i) => lines[i]?.answers.includes(field));
    if (match !== undefined) return match;
  }
  return unused[0] ?? null;
}
