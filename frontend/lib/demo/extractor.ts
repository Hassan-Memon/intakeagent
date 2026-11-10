/**
 * TypeScript port of the backend's RuleBasedExtractor
 * (backend/intakeagent/graph/extractors.py), used by the in-browser demo.
 *
 * It runs on the full merged transcript every turn, keeps earlier values when a re-extraction
 * leaves a field empty, and resolves evidence quotes to character spans, exactly like the
 * Python version. Regexes are kept as close to the originals as JavaScript allows; the only
 * structural change is that Python's scoped `(?i:...)` group is spelled out case by case.
 */

import type { Evidence, Extracted, IntakeRecord, Vertical } from "../types";
import { FIELD_SPECS } from "./schemas";

type Fields = Record<string, Extracted>;

// ---------------------------------------------------------------------------
// Shared patterns
// ---------------------------------------------------------------------------

const MONTH_LIST = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
];
const MONTH_NAMES: Record<string, number> = {};
MONTH_LIST.forEach((m, i) => {
  MONTH_NAMES[m] = i + 1;
});
MONTH_LIST.forEach((m, i) => {
  MONTH_NAMES[m.slice(0, 3)] = i + 1;
});
MONTH_NAMES.sept = 9;

const MONTHS_RE = Object.keys(MONTH_NAMES)
  .sort((a, b) => b.length - a.length)
  .join("|");

const DATE_SRC =
  `(\\d{4}-\\d{2}-\\d{2}|\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}|` +
  `(?:${MONTHS_RE})\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?,?\\s+\\d{4}|` +
  `\\d{1,2}(?:st|nd|rd|th)?\\s+(?:of\\s+)?(?:${MONTHS_RE})\\.?,?\\s+\\d{4})`;

const DATE_RE = new RegExp(DATE_SRC, "i");
const PHONE_RE =
  /(?<![\w-])((?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4})(?![\w-])/;
const EMAIL_RE = /([\w.+-]+@[\w-]+(?:\.[\w-]+)+)/;
const ADDRESS_RE = new RegExp(
  "(\\d{1,6}\\s+(?:[A-Z][a-zA-Z]+\\s+){1,3}" +
    "(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl)" +
    "\\b\\.?(?:,\\s*[A-Z][a-zA-Z]+(?:\\s[A-Z][a-zA-Z]+)?)?)",
);

/** Case-insensitive literal without making the rest of the pattern case-insensitive. */
function ci(literal: string): string {
  return literal.replace(/[a-z]/gi, (c) => `[${c.toLowerCase()}${c.toUpperCase()}]`);
}

const NAME_PREFIX = ["my name is", "my name's", "name is", "this is", "i am", "i'm"]
  .map(ci)
  .join("|");
const NAME_SRC = `(?:${NAME_PREFIX})\\s+([A-Z][a-zA-Z'-]+(?:\\s+[A-Z][a-zA-Z'-]+){1,2})`;

const NUMBER_WORDS: Record<string, number> = {
  one: 1,
  two: 2,
  three: 3,
  four: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  nine: 9,
  ten: 10,
};

// ---------------------------------------------------------------------------
// Small Python-compatible helpers
// ---------------------------------------------------------------------------

function stripChars(s: string, chars: string): string {
  let start = 0;
  let end = s.length;
  while (start < end && chars.includes(s[start] as string)) start++;
  while (end > start && chars.includes(s[end - 1] as string)) end--;
  return s.slice(start, end);
}

function rstripChars(s: string, chars: string): string {
  let end = s.length;
  while (end > 0 && chars.includes(s[end - 1] as string)) end--;
  return s.slice(0, end);
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

function pad(n: number, width: number): string {
  return String(n).padStart(width, "0");
}

function ex(value: unknown, quote: string, confidence = 0.6): Extracted {
  const ev: Evidence = { quote: quote.trim(), start: -1, end: -1, segment_id: null };
  return { value, evidence: [ev], confidence };
}

function sentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function normalizeDate(raw: string): string {
  const s = rstripChars(raw.trim(), ".,");
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  let m = /^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$/.exec(s);
  if (m) {
    const mm = Number(m[1]);
    const dd = Number(m[2]);
    let yy = Number(m[3]);
    if (yy < 100) yy += yy > 30 ? 1900 : 2000;
    return `${pad(yy, 4)}-${pad(mm, 2)}-${pad(dd, 2)}`;
  }
  m = new RegExp(`^(${MONTHS_RE})\\.?\\s+(\\d{1,2})(?:st|nd|rd|th)?,?\\s+(\\d{4})$`, "i").exec(s);
  if (m) {
    const month = MONTH_NAMES[(m[1] as string).toLowerCase()] ?? 0;
    return `${pad(Number(m[3]), 4)}-${pad(month, 2)}-${pad(Number(m[2]), 2)}`;
  }
  m = new RegExp(
    `^(\\d{1,2})(?:st|nd|rd|th)?\\s+(?:of\\s+)?(${MONTHS_RE})\\.?,?\\s+(\\d{4})$`,
    "i",
  ).exec(s);
  if (m) {
    const month = MONTH_NAMES[(m[2] as string).toLowerCase()] ?? 0;
    return `${pad(Number(m[3]), 4)}-${pad(month, 2)}-${pad(Number(m[1]), 2)}`;
  }
  return s;
}

// ---------------------------------------------------------------------------
// Shared record helpers (Extracted.present, merge_records, attach_evidence)
// ---------------------------------------------------------------------------

export function emptyField(): Extracted {
  return { value: null, evidence: [], confidence: 0 };
}

export function isPresent(field: Extracted | undefined): boolean {
  const v = field?.value;
  if (v === null || v === undefined) return false;
  if (typeof v === "string") return v.trim().length > 0;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.keys(v).length > 0;
  return true;
}

/** Normalise list items the way Pydantic does when it validates Medication, Allergy, KeyDate. */
function normaliseValue(name: string, value: unknown): unknown {
  if (!Array.isArray(value)) return value;
  const pick = (item: unknown, keys: string[]) => {
    const obj = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
    return Object.fromEntries(keys.map((k) => [k, obj[k] ?? null]));
  };
  if (name === "medications") return value.map((i) => pick(i, ["name", "dose", "frequency"]));
  if (name === "allergies") return value.map((i) => pick(i, ["substance", "reaction"]));
  if (name === "key_dates") return value.map((i) => pick(i, ["label", "date"]));
  return value;
}

/** Equivalent of `schema(**data).model_dump()`: every field present, in declaration order. */
export function buildRecord(vertical: Vertical, data: Fields): IntakeRecord {
  const out: IntakeRecord = {};
  for (const spec of FIELD_SPECS[vertical]) {
    const f = data[spec.name];
    out[spec.name] = f
      ? {
          value: normaliseValue(spec.name, f.value ?? null),
          evidence: (f.evidence ?? []).map((e) => ({
            quote: e.quote,
            start: e.start ?? -1,
            end: e.end ?? -1,
            segment_id: e.segment_id ?? null,
          })),
          confidence: typeof f.confidence === "number" ? f.confidence : 0,
        }
      : emptyField();
  }
  return out;
}

export function missingRequired(vertical: Vertical, record: IntakeRecord): string[] {
  return FIELD_SPECS[vertical]
    .filter((s) => s.required && !isPresent(record[s.name]))
    .map((s) => s.name);
}

function mergeRecords(
  vertical: Vertical,
  previous: IntakeRecord | null,
  current: IntakeRecord,
): IntakeRecord {
  if (!previous) return current;
  for (const spec of FIELD_SPECS[vertical]) {
    const prev = previous[spec.name];
    if (!isPresent(current[spec.name]) && prev && isPresent(prev)) {
      current[spec.name] = structuredClone(prev);
    }
  }
  return current;
}

function attachEvidence(vertical: Vertical, record: IntakeRecord, transcript: string): IntakeRecord {
  const lowered = transcript.toLowerCase();
  for (const spec of FIELD_SPECS[vertical]) {
    for (const ev of record[spec.name]?.evidence ?? []) {
      if (!ev.quote) continue;
      const idx = lowered.indexOf(ev.quote.toLowerCase());
      if (idx >= 0) {
        ev.start = idx;
        ev.end = idx + ev.quote.length;
      }
    }
  }
  return record;
}

// ---------------------------------------------------------------------------
// Rule-based extraction
// ---------------------------------------------------------------------------

function contact(text: string): Fields {
  const out: Fields = {};
  const phone = PHONE_RE.exec(text);
  if (phone) out.phone = ex((phone[1] as string).replace(/[\s.]/g, "-"), phone[0], 0.8);
  const email = EMAIL_RE.exec(text);
  if (email) out.email = ex(email[1], email[0], 0.9);
  const address = ADDRESS_RE.exec(text);
  if (address) out.address = ex(address[1], address[0], 0.6);
  return out;
}

function extractName(text: string): Extracted | null {
  for (const m of text.matchAll(new RegExp(NAME_SRC, "g"))) {
    const candidate = m[1] as string;
    const tokens = candidate.split(/\s+/).filter(Boolean);
    if (tokens.every((t) => /[A-Z]/.test(t[0] as string))) return ex(candidate, m[0], 0.8);
  }
  return null;
}

function healthcare(text: string): Fields {
  const out = contact(text);
  const name = extractName(text);
  if (name) out.full_name = name;

  const dob = new RegExp(
    `(?:born on|born|date of birth is|dob is|birthday is)\\s+${DATE_SRC}`,
    "i",
  ).exec(text);
  if (dob) out.date_of_birth = ex(normalizeDate(dob[1] as string), dob[0], 0.8);

  const sex = /\b(?:i am|i'm)\s+(?:a\s+)?(male|female|man|woman)\b/i.exec(text);
  if (sex) {
    const raw = sex[1] as string;
    const mapped = ({ man: "male", woman: "female" } as Record<string, string>)[raw.toLowerCase()];
    out.sex = ex((mapped ?? raw).toLowerCase(), sex[0], 0.6);
  }

  const complaint = new RegExp(
    "(?:i've had|i have had|i've been having|i have been having|i am having|i'm having|" +
      "i've got|i have got|suffering from|here for|here because of|" +
      "came in (?:for|because of)|" +
      "complaining of|i have)\\s+(?:a\\s+|an\\s+|some\\s+)?(.+?)" +
      "(?=\\s+(?:since|for the|starting|that started|which started)\\b|[,.]|$)",
    "i",
  ).exec(text);
  if (complaint && !/^(?:no|any|been|an? appointment)/i.test(complaint[1] as string)) {
    out.chief_complaint = ex(complaint[1], complaint[0], 0.6);
  }

  const onset = new RegExp(
    "\\b(?:since|started|starting|began|for the (?:last|past))\\s+" +
      "((?:[A-Za-z]+\\s+){0,2}?(?:yesterday|today|morning|evening|night|afternoon|" +
      "week|weeks|day|days|month|months|year|years|ago|monday|tuesday|wednesday|" +
      "thursday|friday|saturday|sunday)[\\w\\s]*?)(?=[,.]|$)",
    "i",
  ).exec(text);
  if (onset) out.symptom_onset = ex((onset[1] as string).trim(), onset[0], 0.6);

  const severity =
    /\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:out of|\/)\s*(?:10|ten)\b/i.exec(
      text,
    );
  if (severity) {
    const raw = (severity[1] as string).toLowerCase();
    const n = NUMBER_WORDS[raw] ?? raw;
    out.symptom_severity = ex(`${n}/10`, severity[0], 0.8);
  }

  const meds =
    /\b(?:i take|i'm taking|i am taking|i'm on|i am on|currently taking|taking)\s+(.+?)(?=[.]|$)/i.exec(
      text,
    );
  if (meds) {
    const items = (meds[1] as string)
      .split(/,|\band\b/)
      .map((p) => p.trim())
      .filter(Boolean);
    const parsed: { name: string; dose: string | null; frequency: string | null }[] = [];
    for (const item of items) {
      const dose = /\d+(?:\.\d+)?\s*(?:mg|milligrams?|mcg|micrograms?|units?|ml)/.exec(item);
      const freq =
        /(once|twice|three times|four times)\s+(?:a|per)\s+(day|week)|daily|every (?:morning|night|evening|day)|at bedtime|as needed|weekly/i.exec(
          item,
        );
      let medName = item;
      for (const seg of [dose, freq]) {
        if (seg) medName = medName.split(seg[0]).join("");
      }
      medName = stripChars(medName.replace(/\s+/g, " "), " ,");
      if (!medName || ["no medications", "nothing"].includes(medName.toLowerCase())) continue;
      parsed.push({
        name: medName,
        dose: dose ? dose[0] : null,
        frequency: freq ? freq[0] : null,
      });
    }
    if (parsed.length) out.medications = ex(parsed, meds[0], 0.6);
  }
  if (/\b(?:no|not taking any|don't take any)\s+medications?\b/i.test(text)) {
    const m = /[^.]*\bmedications?\b[^.]*/i.exec(text);
    out.medications = ex([{ name: "None reported" }], m ? m[0] : "", 0.7);
  }

  const allergy =
    /\b(?:allergic to|allergy to|allergies to|allergies (?:are|include))\s+(.+?)(?=[.]|$)/i.exec(
      text,
    );
  if (allergy) {
    const clause = allergy[1] as string;
    const reaction = /(?:it gives me|gives me|causes|i get|makes me|i break out in)\s+([\w\s]+)/i.exec(
      clause,
    );
    const head = clause.split(/,\s*(?:it|which|that)\b/)[0] ?? "";
    const parsed = head
      .split(/,|\band\b/)
      .filter((s) => s.trim())
      .map((s) => ({
        substance: s.trim(),
        reaction: reaction ? (reaction[1] as string).trim() : null,
      }));
    if (parsed.length) out.allergies = ex(parsed, allergy[0], 0.6);
  }
  if (/\bno (?:known )?allergies\b/i.test(text)) {
    const m = /[^.]*\bno (?:known )?allergies\b[^.]*/i.exec(text);
    out.allergies = ex([{ substance: "No known allergies" }], m ? m[0] : "", 0.8);
  }

  const conditionsRe =
    /(?:diagnosed with|history of|i have|i'm|i am)\s+((?:type\s*[12]\s+)?(?:diabetes|diabetic|hypertension|high blood pressure|asthma|copd|epilepsy|depression|anxiety|arthritis|heart disease|kidney disease|cancer|migraines?|hypothyroidism))/gi;
  const conditions = [...text.matchAll(conditionsRe)].map((m) => m[1] as string);
  if (conditions.length) {
    const quote = /[^.]*(?:diagnosed with|history of)[^.]*/i.exec(text);
    const unique = [...new Set(conditions.map((c) => c.trim()))].sort();
    out.conditions = ex(unique, quote ? quote[0] : (conditions[0] as string), 0.5);
  }

  const payer =
    /\b(?:insurance (?:is|provider is|company is|is with|with)|insured (?:by|with|through)|covered (?:by|through)|i have|i'm with)\s+([A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*){0,3})/.exec(
      text,
    );
  if (payer) out.insurance_payer = ex(stripChars(payer[1] as string, " ,"), payer[0], 0.7);
  const member = /\bmember (?:id|number)(?: is)?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,})/i.exec(text);
  if (member) out.insurance_member_id = ex(member[1], member[0], 0.8);
  return out;
}

const MATTER_KEYWORDS: [string, string[]][] = [
  [
    "Employment",
    [
      "employment",
      "fired",
      "terminated",
      "wrongful termination",
      "employer",
      "discrimination",
      "harassment",
      "unpaid wages",
      "severance",
    ],
  ],
  ["Personal injury", ["accident", "injured", "injury", "slip", "fell", "crash", "collision"]],
  ["Contract dispute", ["contract", "breach", "agreement", "unpaid invoice", "vendor"]],
  ["Family", ["divorce", "custody", "child support", "separation", "alimony"]],
  ["Real estate", ["landlord", "tenant", "eviction", "lease", "property line"]],
  ["Immigration", ["visa", "green card", "deportation", "immigration", "asylum"]],
  ["Criminal defense", ["arrested", "charged with", "dui", "police"]],
  ["Estate planning", ["will", "estate", "probate", "trust", "inheritance"]],
];

function legal(text: string): Fields {
  const out = contact(text);
  const name = extractName(text);
  if (name) out.client_name = name;

  const explicit =
    /\b(?:this is an?|it's an?|it is an?|i need help with an?|i have an?)\s+([\w\s-]+?)\s+(?:matter|case|issue|dispute|claim)\b/i.exec(
      text,
    );
  if (explicit) {
    out.matter_type = ex(capitalize((explicit[1] as string).trim()), explicit[0], 0.8);
  } else {
    const lowered = text.toLowerCase();
    for (const [label, keys] of MATTER_KEYWORDS) {
      const hit = keys.find((k) => lowered.includes(k));
      if (hit) {
        const sentence = sentences(text).find((s) => s.toLowerCase().includes(hit)) ?? hit;
        out.matter_type = ex(label, sentence, 0.5);
        break;
      }
    }
  }

  const nameRe = new RegExp(NAME_SRC);
  const narrative = sentences(text).filter(
    (s) =>
      /\b(?:i was|they|he|she|the company|my employer|happened|after|because)\b/i.test(s) &&
      !nameRe.test(s),
  );
  if (narrative.length) {
    out.matter_description = ex(narrative.slice(0, 2).join(" "), narrative[0] as string, 0.5);
  }

  const opposing =
    /\b(?:other party is|opposing party is|against|suing|sued by|dispute with|fired (?:by|from)|terminated (?:by|from)|employed by|my employer,?|my landlord,?)\s+([A-Z][\w&'.-]*(?:\s+[A-Z][\w&'.-]*){0,4})/.exec(
      text,
    );
  if (opposing) out.opposing_party = ex(stripChars(opposing[1] as string, " ,."), opposing[0], 0.7);

  const dates: { label: string; date: string }[] = [];
  for (const m of text.matchAll(new RegExp(DATE_SRC, "gi"))) {
    const before = text.slice(0, m.index).trimEnd();
    const parts = before.split(/[.,;]/);
    const clause = parts[parts.length - 1] ?? "";
    const words = clause.split(/\s+/).filter(Boolean).slice(-6);
    let label = words.join(" ").trim() || "date";
    label = label.replace(/\b(?:on|by|at|in)$/, "").trim() || "date";
    dates.push({ label, date: normalizeDate(m[1] as string) });
  }
  if (dates.length) {
    const first = sentences(text).find((s) => DATE_RE.test(s)) ?? "";
    out.key_dates = ex(dates, first, 0.6);
  }

  const names: string[] = [];
  if (out.client_name) names.push(out.client_name.value as string);
  if (out.opposing_party) names.push(out.opposing_party.value as string);
  for (const m of text.matchAll(
    /\bmy\s+(?:manager|boss|supervisor|wife|husband|partner|spouse|ex|landlord|tenant|colleague|neighbou?r|business partner)\s+([A-Z][\w'-]+\s+[A-Z][\w'-]+)/g,
  )) {
    names.push(m[1] as string);
  }
  for (const m of text.matchAll(
    /\b((?:[A-Z][\w&'-]+\s+){1,3}(?:Inc|LLC|Ltd|Limited|Corp|Corporation|Company|Co|Group|Logistics|Holdings|Bank|Hospital|Clinic|Partners|Associates)\b\.?)/g,
  )) {
    names.push(rstripChars(m[1] as string, "."));
  }
  const unique: string[] = [];
  for (const n of names) if (n && !unique.includes(n)) unique.push(n);
  if (unique.length) {
    const quote = out.opposing_party
      ? (out.opposing_party.evidence[0]?.quote ?? "")
      : (unique[0] as string);
    out.conflict_check_names = ex(unique, quote, 0.6);
  }

  const where =
    /\b(?:happened|occurred|took place|based|located|live|work)\s+in\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?(?:,\s*[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)?)/.exec(
      text,
    );
  if (where) out.jurisdiction = ex(rstripChars(where[1] as string, "."), where[0], 0.6);

  const urgency = sentences(text).find((s) =>
    /\b(?:deadline|court date|hearing|urgent|statute of limitations)\b/i.test(s),
  );
  if (urgency) out.urgency = ex(urgency, urgency, 0.5);
  return out;
}

/** RuleBasedExtractor.extract: transcript in, merged record with evidence spans out. */
export function extractRecord(
  transcript: string,
  vertical: Vertical,
  previous: IntakeRecord | null,
): IntakeRecord {
  const data = vertical === "healthcare" ? healthcare(transcript) : legal(transcript);
  const record = mergeRecords(vertical, previous, buildRecord(vertical, data));
  return attachEvidence(vertical, record, transcript);
}
