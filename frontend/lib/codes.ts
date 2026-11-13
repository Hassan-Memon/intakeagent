import type { IntakeRecord, ReviewerCodes } from "./types";

// `codes` travels inside the record (PatientIntake.codes on the backend) but is not an
// Extracted field, so it is read and written through these two helpers instead of widening
// IntakeRecord for every other field.

export function emptyCodes(): ReviewerCodes {
  return { medications: {}, allergies: {}, chief_complaint: {}, conditions: {} };
}

export function codesOf(record: IntakeRecord | null | undefined): ReviewerCodes {
  const raw = (record as Record<string, unknown> | null | undefined)?.codes as
    | Partial<ReviewerCodes>
    | undefined;
  return { ...emptyCodes(), ...(raw ?? {}) };
}

export function withCodes(record: IntakeRecord, codes: ReviewerCodes): IntakeRecord {
  return { ...record, codes } as unknown as IntakeRecord;
}

/** Fields of the record that are Extracted values (everything except `codes`). */
export function withoutCodes(record: IntakeRecord): IntakeRecord {
  const { codes: _codes, ...rest } = record as Record<string, unknown>;
  void _codes;
  return rest as IntakeRecord;
}
