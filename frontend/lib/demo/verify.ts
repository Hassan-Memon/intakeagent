/**
 * In-browser port of backend/intakeagent/verify for the static demo.
 *
 * Same logic, same data: `data/terminology.json` is the NLM snapshot the backend bundles
 * (written by `python -m intakeagent.verify.terminology snapshot`) and `data/sanctions.json` is
 * the backend's fictional demo list. A backend test keeps both copies identical. Nothing is
 * fetched; the demo's promise that nothing leaves the page still holds.
 */

import type {
  Coding,
  DrugCheck,
  IcdCheck,
  IntakeRecord,
  SanctionsMatch,
  SanctionsResult,
  SanctionsScreening,
  Verification,
  VerificationFlag,
  Vertical,
} from "../types";
import sanctionsData from "./data/sanctions.json";
import snapshot from "./data/terminology.json";

const ICD10CM_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm";

interface DrugClass {
  id: string;
  name: string;
  source: string;
}

interface DrugInfo {
  query: string;
  rxcui: string;
  name: string;
  ingredients: Coding[];
  classes: DrugClass[];
}

// ---------------------------------------------------------------------------
// String helpers (difflib.SequenceMatcher.ratio, Ratcliff/Obershelp)
// ---------------------------------------------------------------------------

function matchingChars(a: string, b: string): number {
  if (!a || !b) return 0;
  let bestLen = 0;
  let bestA = 0;
  let bestB = 0;
  // Longest common substring by dynamic programming (strings here are short).
  let prev = new Array<number>(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) {
    const cur = new Array<number>(b.length + 1).fill(0);
    for (let j = 1; j <= b.length; j++) {
      if (a[i - 1] === b[j - 1]) {
        cur[j] = (prev[j - 1] ?? 0) + 1;
        if ((cur[j] ?? 0) > bestLen) {
          bestLen = cur[j] ?? 0;
          bestA = i - bestLen;
          bestB = j - bestLen;
        }
      }
    }
    prev = cur;
  }
  if (bestLen === 0) return 0;
  return (
    bestLen +
    matchingChars(a.slice(0, bestA), b.slice(0, bestB)) +
    matchingChars(a.slice(bestA + bestLen), b.slice(bestB + bestLen))
  );
}

function ratio(a: string, b: string): number {
  const total = a.length + b.length;
  return total === 0 ? 1 : (2 * matchingChars(a, b)) / total;
}

export function normalizeTerm(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9/ ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function similarity(a: string, b: string): number {
  return ratio(normalizeTerm(a), normalizeTerm(b));
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// ---------------------------------------------------------------------------
// Offline terminology (OfflineTerminologyClient)
// ---------------------------------------------------------------------------

const DRUGS = snapshot.drugs as DrugInfo[];
const ALIASES: Record<string, string> = Object.fromEntries(
  Object.entries(snapshot.aliases as Record<string, string>).map(([k, v]) => [normalizeTerm(k), v]),
);
const ICD: Coding[] = (snapshot.icd10cm as { code: string; display: string }[]).map((r) => ({
  system: ICD10CM_SYSTEM,
  ...r,
}));

function lookupDrug(term: string): DrugInfo | null {
  let norm = normalizeTerm(term);
  if (!norm) return null;
  norm = ALIASES[norm] ?? norm;
  let best: [number, DrugInfo] | null = null;
  for (const drug of DRUGS) {
    const names = [drug.query, drug.name, ...drug.ingredients.map((i) => i.display)];
    for (const candidate of names) {
      const cand = normalizeTerm(candidate);
      let score = cand === norm ? 1 : similarity(norm, cand);
      if (cand && new RegExp(`\\b${escapeRe(cand)}\\b`).test(norm)) score = Math.max(score, 0.95);
      if (!best || score > best[0]) best = [score, drug];
    }
  }
  if (!best || best[0] < 0.8) return null;
  return { ...best[1], query: term };
}

function searchIcd10(query: string, limit = 5): Coding[] {
  const norm = normalizeTerm(query);
  const words = norm.split(" ").filter(Boolean);
  if (!words.length) return [];
  const hits: [number, number, Coding][] = [];
  for (const row of ICD) {
    const name = normalizeTerm(row.display);
    const nameWords = name.split(" ");
    if (words.every((w) => nameWords.some((nw) => nw.startsWith(w)))) {
      const phrase = new RegExp(`\\b${escapeRe(norm)}`).test(name) ? 0 : 1;
      hits.push([phrase, name.length, row]);
    }
  }
  hits.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  return hits.slice(0, limit).map((h) => h[2]);
}

// ---------------------------------------------------------------------------
// Clinical checks (verify/clinical.py)
// ---------------------------------------------------------------------------

const ALLERGEN_CLASS_TERMS: Record<string, string[]> = {
  penicillin: ["penicillin"],
  penicillins: ["penicillin"],
  sulfa: ["sulfonamide"],
  "sulfa drugs": ["sulfonamide"],
  sulfonamides: ["sulfonamide"],
  nsaid: ["nonsteroidal anti-inflammatory"],
  nsaids: ["nonsteroidal anti-inflammatory"],
  "anti inflammatories": ["nonsteroidal anti-inflammatory"],
  cephalosporins: ["cephalosporin"],
  opioids: ["opioid"],
  opiates: ["opioid"],
  statins: ["hmg-coa reductase"],
  "ace inhibitors": ["angiotensin converting enzyme"],
  macrolides: ["macrolide"],
  tetracyclines: ["tetracycline"],
  quinolones: ["quinolone"],
  fluoroquinolones: ["quinolone"],
};

const NON_DRUG_ALLERGENS = new Set([
  "latex", "peanut", "peanuts", "tree nuts", "shellfish", "eggs", "egg", "milk", "dairy",
  "soy", "wheat", "gluten", "bees", "bee stings", "pollen", "dust", "cats", "dogs",
]);

const COMPLAINT_SYNONYMS: [RegExp, string][] = [
  [/\b(?:lower right|right lower)\s+(?:side|abdomen|belly|stomach|tummy)\b/g, "right lower quadrant"],
  [/\b(?:lower left|left lower)\s+(?:side|abdomen|belly|stomach|tummy)\b/g, "left lower quadrant"],
  [/\b(?:upper right|right upper)\s+(?:side|abdomen|belly|stomach|tummy)\b/g, "right upper quadrant"],
  [/\b(?:upper left|left upper)\s+(?:side|abdomen|belly|stomach|tummy)\b/g, "left upper quadrant"],
  [/\b(?:stomach|belly|tummy)\s*(?:ache|pain)s?\b/g, "abdominal pain"],
  [/\b(?:stomach|belly|tummy)\b/g, "abdominal"],
  [/\bthrowing up\b|\bbeing sick\b/g, "vomiting"],
  [/\bfeeling sick\b|\bqueasy\b/g, "nausea"],
  [/\bshort(?:ness)? of breath\b|\btrouble breathing\b|\bcan'?t breathe\b/g, "shortness breath"],
  [/\bhead\s*aches?\b|\bmy head hurts\b/g, "headache"],
  [/\bsore throat\b/g, "pharyngitis"],
  [/\bear\s*ache\b/g, "otalgia"],
  [/\bhigh blood pressure\b/g, "essential hypertension"],
  [/\bcan'?t sleep\b|\btrouble sleeping\b/g, "insomnia"],
  [/\b(?:lower|low) back\b/g, "low back"],
  [/\bdiabetic\b/g, "diabetes"],
  [/\bsugar\b/g, "diabetes"],
];

const STOPWORDS = new Set([
  "a", "an", "the", "i", "i've", "ive", "my", "me", "have", "had", "has", "been", "having",
  "in", "on", "of", "at", "to", "for", "with", "and", "or", "some", "really", "very", "bad",
  "sharp", "dull", "terrible", "awful", "little", "bit", "kind", "sort", "since", "it", "its",
  "is", "this", "that", "feel", "feeling", "got", "getting", "keep", "keeps", "side", "area",
  "constant", "severe", "mild", "slight", "sudden", "lot", "pretty", "quite", "like", "around",
]);

export function complaintQuery(text: string): string {
  let s = text.toLowerCase();
  for (const [pattern, repl] of COMPLAINT_SYNONYMS) s = s.replace(pattern, repl);
  return (s.match(/[a-z0-9']+/g) ?? []).filter((w) => !STOPWORDS.has(w)).join(" ");
}

function icdSuggestions(text: string, limit = 5): IcdCheck {
  const query = complaintQuery(text);
  const words = query.split(" ").filter(Boolean);
  const tried: string[] = [];
  for (let size = words.length; size > 0; size--) {
    for (let start = 0; start + size <= words.length; start++) {
      const q = words.slice(start, start + size).join(" ");
      if (tried.includes(q)) continue;
      tried.push(q);
      const hits = searchIcd10(q, limit);
      if (hits.length) return { input: text, query: q, suggestions: hits, status: "matched" };
      if (tried.length >= 6) return { input: text, query, suggestions: [], status: "no_match" };
    }
  }
  return { input: text, query, suggestions: [], status: "no_match" };
}

function stripDose(name: string): string {
  return name.replace(/\b\d+(?:\.\d+)?\s*(?:mg|milligrams?|mcg|micrograms?|ml|units?)\b/gi, "");
}

function drugEntry(info: DrugInfo | null, spoken: string): DrugCheck {
  if (!info) return { input: spoken, status: "no_match", match: null };
  const names = [info.name, ...info.ingredients.map((i) => i.display)];
  let confidence = Math.max(...names.map((n) => similarity(stripDose(spoken), n)));
  if (names.some((n) => normalizeTerm(spoken).includes(normalizeTerm(n)))) {
    confidence = Math.max(confidence, 0.95);
  }
  return {
    input: spoken,
    status: "matched",
    match: { system: "http://www.nlm.nih.gov/research/umls/rxnorm", code: info.rxcui, display: info.name },
    ingredients: info.ingredients,
    classes: info.classes.map((c) => c.name),
    confidence: Math.round(confidence * 100) / 100,
  };
}

function allergyFlag(
  allergen: string,
  allergenInfo: DrugInfo | null,
  medName: string,
  med: DrugInfo,
): VerificationFlag | null {
  const aNorm = normalizeTerm(allergen);
  const medIngredients = new Map(med.ingredients.map((i) => [i.code, i.display]));
  let reason: string | null = null;
  let kind: VerificationFlag["kind"] = "allergy_class";

  if (allergenInfo) {
    const shared = allergenInfo.ingredients.find((i) => medIngredients.has(i.code));
    if (shared) {
      kind = "allergy_ingredient";
      reason = `${medName} contains ${medIngredients.get(shared.code)}`;
    }
  }
  if (!reason) {
    for (const display of medIngredients.values()) {
      if (normalizeTerm(display) === aNorm) {
        kind = "allergy_ingredient";
        reason = `${medName} contains ${display}`;
        break;
      }
    }
  }
  if (!reason) {
    const terms = ALLERGEN_CLASS_TERMS[aNorm] ?? [aNorm.replace(/s+$/, "")];
    const cls = med.classes.find((c) => terms.some((t) => t && c.name.toLowerCase().includes(t)));
    if (cls) reason = `${medName} is in the class “${cls.name}”`;
  }
  if (!reason && allergenInfo) {
    const ids = new Set(allergenInfo.classes.map((c) => c.id));
    const cls = med.classes.find((c) => ids.has(c.id));
    if (cls) reason = `${medName} and ${allergen} share the class “${cls.name}”`;
  }
  if (!reason) return null;
  return {
    id: `${kind}:${aNorm}:${normalizeTerm(medName)}`,
    kind,
    severity: kind === "allergy_ingredient" ? "high" : "warning",
    title: `${medName} may conflict with the reported ${allergen} allergy`,
    detail:
      `${reason} (RxNorm/RxClass). Confirm with the patient or clinician before approving; ` +
      "this is a reference check, not a clinical judgement.",
    fields: ["medications", "allergies"],
  };
}

function items(record: IntakeRecord, field: string, attr: string): string[] {
  const value = record[field]?.value;
  if (!Array.isArray(value)) return [];
  return value
    .map((v) => (v && typeof v === "object" ? (v as Record<string, unknown>)[attr] : null))
    .filter((v): v is string => typeof v === "string" && v.trim() !== "");
}

function verifyPatient(record: IntakeRecord): Omit<Verification, "vertical" | "sources"> {
  const medications: DrugCheck[] = [];
  const medInfos: [string, DrugInfo][] = [];
  for (const name of items(record, "medications", "name")) {
    if (name.toLowerCase().startsWith("none")) continue;
    let info = lookupDrug(stripDose(name));
    const bare = stripDose(name).replace(/\b\d+(?:\.\d+)?\b/g, "").replace(/\s+/g, " ");
    if (!info && bare.trim() !== stripDose(name).trim()) info = lookupDrug(bare);
    medications.push(drugEntry(info, name));
    if (info) medInfos.push([name, info]);
  }

  const allergies: DrugCheck[] = [];
  const flags: VerificationFlag[] = [];
  for (const substance of items(record, "allergies", "substance")) {
    const aNorm = normalizeTerm(substance);
    if (aNorm.startsWith("no known") || aNorm.startsWith("none")) continue;
    if (NON_DRUG_ALLERGENS.has(aNorm)) {
      allergies.push({ input: substance, status: "not_a_drug", match: null });
      continue;
    }
    let info: DrugInfo | null = null;
    if (ALLERGEN_CLASS_TERMS[aNorm]) {
      allergies.push({
        input: substance,
        status: "drug_class",
        match: null,
        classes: ALLERGEN_CLASS_TERMS[aNorm],
      });
    } else {
      info = lookupDrug(substance);
      const entry = drugEntry(info, substance);
      allergies.push(entry);
      if ((entry.confidence ?? 0) < 0.6) info = null;
    }
    for (const [medName, medInfo] of medInfos) {
      const flag = allergyFlag(substance, info, medName, medInfo);
      if (flag) flags.push(flag);
    }
  }

  const complaint = record.chief_complaint?.value;
  const conditions = record.conditions?.value;
  return {
    medications,
    allergies,
    chief_complaint: typeof complaint === "string" && complaint ? icdSuggestions(complaint) : null,
    conditions: Array.isArray(conditions) ? conditions.map((c) => icdSuggestions(String(c))) : [],
    flags,
    errors: [],
  };
}

// ---------------------------------------------------------------------------
// Sanctions screening (verify/sanctions.py)
// ---------------------------------------------------------------------------

const POSSIBLE = 0.85;
const STRONG = 0.97;
const LEGAL_SUFFIXES = new Set([
  "ltd", "limited", "llc", "inc", "incorporated", "co", "company", "corp", "corporation",
  "plc", "sa", "gmbh", "ag", "bv", "nv", "llp", "lp", "fze", "fzco", "fzc", "jsc", "pjsc",
  "ojsc", "cjsc", "ooo", "sarl", "srl", "spa", "pte", "pty", "the", "of", "and",
]);

export function normalizeName(name: string): string[] {
  const s = name
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]/gu, " ");
  return s.split(/\s+/).filter((t) => t && !LEGAL_SUFFIXES.has(t));
}

function tokenSim(a: string, b: string): number {
  if (a === b) return 1;
  if (a.length < 3 || b.length < 3) return 0;
  return ratio(a, b);
}

export function nameScore(query: string[], candidate: string[]): number {
  if (!query.length || !candidate.length) return 0;
  const cover = (xs: string[], ys: string[]) =>
    xs.reduce((sum, x) => sum + Math.max(...ys.map((y) => tokenSim(x, y))), 0) / xs.length;
  return 0.7 * cover(query, candidate) + 0.3 * cover(candidate, query);
}

interface SanctionsEntry {
  id: string;
  list: string;
  name: string;
  type: string;
  program: string;
  aliases: string[];
}

const LIST = sanctionsData as {
  name: string;
  generated_at: string;
  demo: boolean;
  sources: { name: string }[];
  entries: SanctionsEntry[];
};
const LIST_TOKENS = LIST.entries.map((e) =>
  [e.name, ...e.aliases].map((n) => [n, normalizeName(n)] as const),
);

function searchSanctions(name: string, limit = 3): SanctionsMatch[] {
  const query = normalizeName(name);
  if (!query.length) return [];
  const prefixes = new Set(query.filter((t) => t.length >= 3).map((t) => t.slice(0, 3)));
  const need = Math.min(2, prefixes.size);
  const out: SanctionsMatch[] = [];
  LIST.entries.forEach((e, i) => {
    const entryPrefixes = new Set(
      (LIST_TOKENS[i] ?? []).flatMap(([, toks]) => toks.filter((t) => t.length >= 3).map((t) => t.slice(0, 3))),
    );
    let shared = 0;
    for (const p of prefixes) if (entryPrefixes.has(p)) shared++;
    if (shared < need || need === 0) return;
    let bestName = "";
    let best = 0;
    for (const [raw, toks] of LIST_TOKENS[i] ?? []) {
      const s = nameScore(query, toks);
      if (s > best) [bestName, best] = [raw, s];
    }
    if (best >= POSSIBLE && (query.length > 1 || best >= STRONG)) {
      out.push({
        entry_id: e.id,
        list: e.list,
        listed_name: e.name,
        matched_name: bestName,
        type: e.type,
        program: e.program,
        score: Math.round(best * 1000) / 1000,
      });
    }
  });
  return out.sort((a, b) => b.score - a.score).slice(0, limit);
}

export function screenRecord(record: IntakeRecord): SanctionsScreening {
  const parties: [string, string][] = [];
  const client = record.client_name?.value;
  const opposing = record.opposing_party?.value;
  if (typeof client === "string" && client) parties.push([client, "client"]);
  if (typeof opposing === "string" && opposing) parties.push([opposing, "opposing party"]);
  const named = record.conflict_check_names?.value;
  if (Array.isArray(named)) for (const n of named) parties.push([String(n), "named party"]);

  const seen = new Set<string>();
  const results: SanctionsResult[] = [];
  for (const [name, role] of parties) {
    const key = normalizeName(name).join(" ");
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const matches = searchSanctions(name);
    const top = matches[0]?.score ?? 0;
    const status = top >= STRONG ? "strong_match" : matches.length ? "possible_match" : "clear";
    results.push({ name, role, status, matches });
  }
  return {
    status: "ok",
    list: {
      name: LIST.name,
      generated_at: LIST.generated_at,
      entry_count: LIST.entries.length,
      demo: LIST.demo,
      sources: LIST.sources.map((s) => s.name),
    },
    results,
  };
}

const ROLE_FIELDS: Record<string, string> = {
  client: "client_name",
  "opposing party": "opposing_party",
  "named party": "conflict_check_names",
};

function verifyLegal(record: IntakeRecord): Omit<Verification, "vertical"> {
  const sanctions = screenRecord(record);
  const flags: VerificationFlag[] = [];
  for (const r of sanctions.results) {
    const top = r.matches[0];
    if (r.status === "clear" || !top) continue;
    const program = top.program ? `, program ${top.program}` : "";
    flags.push({
      id: `sanctions:${normalizeName(r.name).join(" ")}`,
      kind: "sanctions_match",
      severity: r.status === "strong_match" ? "high" : "warning",
      title: `${r.name} (${r.role}) resembles a sanctions-list entry`,
      detail:
        `Closest entry: ${top.matched_name} (${top.list}${program}), similarity ` +
        `${top.score.toFixed(2)}. Confirm identity (date of birth, address, nationality, ` +
        "registration number) before opening the matter. A similar name is not a match on its own.",
      fields: [ROLE_FIELDS[r.role] ?? "conflict_check_names"],
    });
  }
  return {
    sanctions,
    flags,
    sources: [{ name: LIST.name, mode: "demo", as_of: LIST.generated_at }],
    errors: [],
  };
}

/** Verifier.verify(): the same JSON the backend's POST /sessions/{id}/verify returns. */
export function verifyRecord(vertical: Vertical, record: IntakeRecord): Verification {
  const checked_at = new Date().toISOString();
  if (vertical === "legal") return { vertical, checked_at, ...verifyLegal(record) };
  return {
    vertical,
    checked_at,
    sources: [
      { name: "RxNorm + RxClass (U.S. National Library of Medicine)", mode: "offline", as_of: snapshot.generated_at },
      { name: "ICD-10-CM (NLM Clinical Tables)", mode: "offline", as_of: snapshot.generated_at },
    ],
    ...verifyPatient(record),
  };
}
