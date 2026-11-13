// Shared types mirroring the backend's Pydantic models and the WebSocket protocol
// (docs/protocol.md). Keeping them in one file makes the contract easy to audit.

export type Vertical = "healthcare" | "legal";

export type SessionStatus = "recording" | "awaiting_approval" | "approved" | "exported";

export interface Evidence {
  quote: string;
  start: number;
  end: number;
  segment_id?: string | null;
}

export interface Extracted<T = unknown> {
  value: T | null;
  evidence: Evidence[];
  confidence: number;
}

export type IntakeRecord = Record<string, Extracted>;

export interface FieldSpec {
  name: string;
  required: boolean;
  question: string;
  group: string;
  description: string;
  kind: "scalar" | "list";
}

export interface TranscriptSegment {
  id: string;
  text: string;
  start_ms: number;
  end_ms: number;
  final?: boolean;
  char_start?: number;
}

export interface Session {
  id: string;
  vertical: Vertical;
  status: SessionStatus;
  created_at: string;
  updated_at: string;
  transcript: string;
  transcript_segments: TranscriptSegment[];
  record: IntakeRecord;
  missing_fields: string[];
  next_question: string | null;
  next_field: string | null;
  field_specs: FieldSpec[];
}

export interface ApprovedRecord {
  id: string;
  session_id: string;
  vertical: Vertical;
  record: IntakeRecord;
  approved_at: string;
  approved_by: string;
  export_target: string | null;
  exported_at: string | null;
  export_result: Record<string, unknown> | null;
}

// Server -> client WebSocket messages.
export type ServerMessage =
  | {
      type: "ready";
      session_id: string;
      vertical: Vertical;
      status: SessionStatus;
      stt: string;
      question: string | null;
      record: IntakeRecord;
      missing_fields: string[];
    }
  | { type: "status"; state: string }
  | { type: "transcript"; segment: TranscriptSegment }
  | { type: "extraction"; record: IntakeRecord; missing_fields: string[] }
  | { type: "question"; text: string; field: string | null }
  | {
      type: "awaiting_approval";
      session_id: string;
      record: IntakeRecord;
      missing_fields: string[];
      review_url: string;
    }
  | { type: "error"; code: string; message: string }
  | { type: "pong" };

// Client -> server JSON control messages (audio goes as binary frames).
export type ClientMessage =
  | { type: "audio_meta"; mime: string; seq: number }
  | { type: "text"; text: string }
  | { type: "finish" }
  | { type: "ping" };

// ---------------------------------------------------------------------------
// Verification (backend/intakeagent/verify, POST /sessions/{id}/verify)
// ---------------------------------------------------------------------------

/** A code from a standard terminology, shaped like a FHIR Coding. */
export interface Coding {
  system: string;
  code: string;
  display: string;
}

/**
 * Codes the reviewer accepted, keyed by the exact text they code. Sent as `record.codes`
 * (PatientIntake.codes). Editing the text afterwards drops the stale code at export.
 */
export interface ReviewerCodes {
  medications: Record<string, Coding>;
  allergies: Record<string, Coding>;
  chief_complaint: Record<string, Coding>;
  conditions: Record<string, Coding>;
}

export interface VerificationFlag {
  id: string;
  kind: "allergy_ingredient" | "allergy_class" | "sanctions_match";
  severity: "high" | "warning";
  title: string;
  detail: string;
  fields: string[];
}

export interface DrugCheck {
  input: string;
  status: "matched" | "no_match" | "error" | "not_a_drug" | "drug_class";
  match: Coding | null;
  ingredients?: Coding[];
  classes?: string[];
  confidence?: number;
}

export interface IcdCheck {
  input: string;
  query: string;
  suggestions: Coding[];
  status: "matched" | "no_match";
}

export interface SanctionsMatch {
  entry_id: string;
  list: string;
  listed_name: string;
  matched_name: string;
  type: string;
  program: string;
  score: number;
}

export interface SanctionsResult {
  name: string;
  role: string;
  status: "clear" | "possible_match" | "strong_match";
  matches: SanctionsMatch[];
}

export interface SanctionsScreening {
  status: "ok" | "unavailable";
  list: {
    name: string;
    generated_at: string;
    entry_count: number;
    demo: boolean;
    sources: string[];
  } | null;
  message?: string;
  results: SanctionsResult[];
}

export interface VerificationSource {
  name: string;
  mode: "live" | "offline" | "local" | "demo";
  as_of?: string | null;
}

export interface Verification {
  vertical: Vertical;
  checked_at?: string;
  sources: VerificationSource[];
  flags: VerificationFlag[];
  errors?: string[];
  // healthcare
  medications?: DrugCheck[];
  allergies?: DrugCheck[];
  chief_complaint?: IcdCheck | null;
  conditions?: IcdCheck[];
  // legal
  sanctions?: SanctionsScreening;
}
