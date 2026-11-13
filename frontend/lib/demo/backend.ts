/**
 * In-browser stand-in for the FastAPI backend, used when NEXT_PUBLIC_DEMO_MODE=1.
 *
 * It mirrors IntakeService (backend/intakeagent/api/service.py) and the intake graph:
 * every typed utterance is appended to the transcript, the TypeScript port of the rule-based
 * extractor re-reads the whole transcript, missing required fields are recomputed and the next
 * question is picked in schema order. State lives in sessionStorage, so it disappears when the
 * tab closes and never leaves the browser.
 */

import { codesOf, withCodes } from "../codes";
import type {
  ApprovedRecord,
  IntakeRecord,
  Session,
  SessionStatus,
  TranscriptSegment,
  Verification,
  Vertical,
} from "../types";
import { exportClio, exportFhir } from "./exporters";
import { buildRecord, extractRecord, missingRequired } from "./extractor";
import { CLOSERS, OPENERS, hintFor, nextQuestion } from "./questions";
import { SAMPLES } from "./samples";
import { FIELD_SPECS } from "./schemas";
import { verifyRecord } from "./verify";

interface StoredSession extends Omit<Session, "field_specs"> {
  questions_asked: string[];
}

interface DemoState {
  version: 1;
  seeded: boolean;
  sessions: Record<string, StoredSession>;
  records: ApprovedRecord[];
}

const STORAGE_KEY = "intakeagent-demo-v1";
let memory: DemoState | null = null;

function fresh(): DemoState {
  return { version: 1, seeded: false, sessions: {}, records: [] };
}

function load(): DemoState {
  if (memory) return memory;
  let state = fresh();
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as DemoState;
      if (parsed && parsed.version === 1) state = parsed;
    }
  } catch {
    // Storage blocked or corrupt: keep an in-memory state for this page.
  }
  memory = state;
  if (!state.seeded) seed(state);
  return state;
}

function save(state: DemoState): void {
  memory = state;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Quota or privacy mode: the in-memory copy still works until reload.
  }
}

export class DemoError extends Error {}

function fail(status: number, detail: string): never {
  throw new DemoError(`${status}: ${detail}`);
}

function hexId(len = 32): string {
  const bytes = new Uint8Array(len / 2);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function nowIso(): string {
  return new Date().toISOString();
}

function toSession(row: StoredSession): Session {
  const { questions_asked: _asked, ...rest } = row;
  void _asked;
  return structuredClone({ ...rest, field_specs: FIELD_SPECS[row.vertical] });
}

function getRow(state: DemoState, id: string): StoredSession {
  const row = state.sessions[id];
  if (!row) fail(404, "session not found");
  return row;
}

/** merge_transcript: segments joined by one space, char_start recorded per segment. */
function mergeTranscript(segments: TranscriptSegment[]): string {
  const parts: string[] = [];
  let offset = 0;
  for (const seg of segments) {
    const text = seg.text.trim();
    seg.char_start = offset;
    parts.push(text);
    offset += text.length + 1;
  }
  return parts.join(" ");
}

/** Roughly how long a line takes to say, so the transcript timeline looks like real audio. */
function speakingMs(text: string): number {
  const words = text.split(/\s+/).filter(Boolean).length;
  return Math.max(1500, Math.round(words * 380));
}

// ---------------------------------------------------------------------------
// Service operations (synchronous; the async API below wraps them)
// ---------------------------------------------------------------------------

function createSessionSync(state: DemoState, vertical: Vertical): StoredSession {
  if (vertical !== "healthcare" && vertical !== "legal") fail(422, "unknown vertical");
  const at = nowIso();
  const row: StoredSession = {
    id: hexId(),
    vertical,
    status: "recording",
    created_at: at,
    updated_at: at,
    transcript: "",
    transcript_segments: [],
    record: {},
    missing_fields: [],
    next_question: OPENERS[vertical],
    next_field: null,
    questions_asked: [],
  };
  state.sessions[row.id] = row;
  return row;
}

export interface TurnResult {
  newSegments: TranscriptSegment[];
  record: IntakeRecord;
  missing: string[];
  question: string | null;
  field: string | null;
}

function addTextSync(state: DemoState, id: string, text: string): TurnResult {
  const row = getRow(state, id);
  if (row.status !== "recording") fail(409, `session is ${row.status}; no more audio accepted`);
  const clean = text.trim();
  const offset = row.transcript_segments.reduce((m, s) => Math.max(m, s.end_ms), 0);
  const seg: TranscriptSegment = {
    id: hexId(8),
    text: clean,
    start_ms: offset,
    end_ms: offset + speakingMs(clean),
    final: true,
  };
  const newSegments = clean ? [seg] : [];
  row.transcript_segments = [...row.transcript_segments, ...newSegments];
  row.transcript = mergeTranscript(row.transcript_segments);

  const previous = Object.keys(row.record).length ? row.record : null;
  row.record = extractRecord(row.transcript, row.vertical, previous);
  row.missing_fields = missingRequired(row.vertical, row.record);

  const hint = row.missing_fields.length ? hintFor(row.vertical, row.missing_fields[0] as string) : null;
  const [question, field] = nextQuestion(
    FIELD_SPECS[row.vertical],
    row.missing_fields,
    row.questions_asked,
    hint,
  );
  row.next_question = question ?? CLOSERS[row.vertical];
  row.next_field = field;
  row.questions_asked = [...row.questions_asked, row.next_question];
  row.updated_at = nowIso();

  return {
    newSegments: structuredClone(newSegments),
    record: structuredClone(row.record),
    missing: [...row.missing_fields],
    question: row.next_question,
    field: row.next_field,
  };
}

function finishSync(state: DemoState, id: string): StoredSession {
  const row = getRow(state, id);
  if (row.status !== "recording" && row.status !== "awaiting_approval") {
    fail(409, `session is ${row.status}`);
  }
  row.transcript = mergeTranscript(row.transcript_segments);
  const previous = Object.keys(row.record).length ? row.record : null;
  row.record = extractRecord(row.transcript, row.vertical, previous);
  row.missing_fields = missingRequired(row.vertical, row.record);
  row.status = "awaiting_approval";
  row.updated_at = nowIso();
  return row;
}

function runExport(row: StoredSession, record: IntakeRecord, target: "fhir" | "clio") {
  return target === "fhir" ? exportFhir(record, row.id) : exportClio(record, row.id);
}

function approveSync(
  state: DemoState,
  id: string,
  edits: IntakeRecord | null,
  exportTarget: "fhir" | "clio" | null,
  approvedBy = "front-desk",
): { status: SessionStatus; record: ApprovedRecord } {
  const row = getRow(state, id);
  if (row.status !== "recording" && row.status !== "awaiting_approval") {
    fail(409, `session is ${row.status}`);
  }
  if (row.status === "recording") finishSync(state, id);
  // buildRecord keeps only schema fields; reviewer codes (healthcare) ride along separately,
  // the way PatientIntake.codes does on the backend.
  const source = edits && Object.keys(edits).length ? edits : row.record;
  row.record = buildRecord(row.vertical, source);
  if (row.vertical === "healthcare") row.record = withCodes(row.record, codesOf(source));
  row.next_question = CLOSERS[row.vertical];
  row.next_field = null;

  const exportResult = exportTarget ? runExport(row, row.record, exportTarget) : null;
  row.status = exportResult ? "exported" : "approved";
  row.updated_at = nowIso();
  const approved: ApprovedRecord = {
    id: hexId(),
    session_id: row.id,
    vertical: row.vertical,
    record: structuredClone(row.record),
    approved_at: nowIso(),
    approved_by: approvedBy,
    export_target: exportResult ? exportTarget : null,
    exported_at: exportResult ? nowIso() : null,
    export_result: exportResult,
  };
  state.records.push(approved);
  return { status: row.status, record: structuredClone(approved) };
}

function verifySync(state: DemoState, id: string, edits: IntakeRecord | null): Verification {
  const row = getRow(state, id);
  const source = edits ?? row.record;
  if (!Object.keys(source).length) fail(409, "nothing to verify yet");
  return verifyRecord(row.vertical, buildRecord(row.vertical, source));
}

function exportSync(state: DemoState, id: string, target: "fhir" | "clio"): Record<string, unknown> {
  if (target !== "fhir" && target !== "clio") fail(409, `unknown export target ${String(target)}`);
  const row = getRow(state, id);
  if (row.status !== "approved" && row.status !== "exported") {
    fail(409, "record must be approved before export");
  }
  const approved = [...state.records]
    .filter((r) => r.session_id === id)
    .sort((a, b) => b.approved_at.localeCompare(a.approved_at))[0];
  if (!approved) fail(409, "no approved record for this session");
  const result = runExport(row, approved.record, target);
  approved.export_target = target;
  approved.export_result = result;
  approved.exported_at = nowIso();
  row.status = "exported";
  row.updated_at = nowIso();
  return structuredClone(result);
}

/** First visit: add one approved record per vertical so the Records page is not empty. */
function seed(state: DemoState): void {
  state.seeded = true;
  const verticals: Vertical[] = ["healthcare", "legal"];
  for (const vertical of verticals) {
    const row = createSessionSync(state, vertical);
    for (const line of SAMPLES[vertical]) addTextSync(state, row.id, line.text);
    finishSync(state, row.id);
    approveSync(state, row.id, null, null, "demo-seed");
  }
  save(state);
}

// ---------------------------------------------------------------------------
// Public API, same shape as lib/api.ts
// ---------------------------------------------------------------------------

function later<T>(fn: () => T, ms = 120): Promise<T> {
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      try {
        resolve(fn());
      } catch (e) {
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    }, ms);
  });
}

function mutate<T>(fn: (state: DemoState) => T): T {
  const state = load();
  const out = fn(state);
  save(state);
  return out;
}

export const demoApi = {
  createSession: (vertical: Vertical) =>
    later(() => toSession(mutate((s) => createSessionSync(s, vertical)))),
  getSession: (id: string) => later(() => toSession(getRow(load(), id))),
  // The backend also takes acknowledged flag ids and audits them; the demo has no audit trail.
  approve: (id: string, record: IntakeRecord, exportTarget?: "fhir" | "clio") =>
    later(() => mutate((s) => approveSync(s, id, record, exportTarget ?? null)), 300),
  verify: (id: string, record?: IntakeRecord) =>
    later(() => verifySync(load(), id, record ?? null), 350),
  exportSession: (id: string, target: "fhir" | "clio") =>
    later(() => mutate((s) => exportSync(s, id, target)), 500),
  listRecords: () =>
    later(() =>
      structuredClone(
        [...load().records]
          .sort((a, b) => b.approved_at.localeCompare(a.approved_at))
          .slice(0, 100),
      ),
    ),
  health: () =>
    later(() => ({
      demo_mode: true,
      llm: "rules (TypeScript port, in your browser)",
      stt: "none in the browser demo (type, or play a sample)",
      llm_local: true,
    })),
};

// Used by the simulated WebSocket.
export const demoService = {
  exists: (id: string) => Boolean(load().sessions[id]),
  session: (id: string) => toSession(getRow(load(), id)),
  addText: (id: string, text: string) => mutate((s) => addTextSync(s, id, text)),
  finish: (id: string) => toSession(mutate((s) => finishSync(s, id))),
};
