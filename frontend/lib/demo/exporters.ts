/**
 * Ports of backend/intakeagent/exporters/fhir.py (build_bundle) and clio.py (mock mode).
 *
 * Output has the same shape as the backend's exporter results. Nothing is sent anywhere: the
 * FHIR result is always a dry run and the Clio result is always a mock with fake ids.
 */

import type { IntakeRecord } from "../types";

type Json = Record<string, unknown>;

const NOT_SENT = "not sent: in-browser demo";

function val(record: IntakeRecord, name: string): unknown {
  const v = record[name]?.value;
  return v === undefined ? null : v;
}

function str(record: IntakeRecord, name: string): string | null {
  const v = val(record, name);
  if (v === null || v === "") return null;
  return String(v);
}

function list<T = Json>(record: IntakeRecord, name: string): T[] {
  const v = val(record, name);
  return Array.isArray(v) ? (v as T[]) : [];
}

/** Drop null/undefined keys, like model_dump(exclude_none=True). */
function compact(obj: Json): Json {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== null && v !== undefined));
}

function urn(): string {
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx".replace(/x/g, () =>
          Math.floor(Math.random() * 16).toString(16),
        );
  return `urn:uuid:${id}`;
}

function entry(resource: Json, fullUrl: string): Json {
  return {
    fullUrl,
    resource,
    request: { method: "POST", url: resource.resourceType },
  };
}

function validDate(value: string | null): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value ? value : null;
}

function splitName(full: string): [string[], string] {
  const parts = full.trim().split(/\s+/).filter(Boolean);
  if (parts.length <= 1) return [[], parts[0] ?? ""];
  return [parts.slice(0, -1), parts[parts.length - 1] as string];
}

const CLINICAL = "http://terminology.hl7.org/CodeSystem/condition-clinical";
const CATEGORY = "http://terminology.hl7.org/CodeSystem/condition-category";

/** build_bundle(): FHIR R4 transaction Bundle from a PatientIntake-shaped record. */
export function buildBundle(record: IntakeRecord, sessionId: string): Json {
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const patientUrl = urn();
  const encounterUrl = urn();
  const entries: Json[] = [];

  const [given, family] = splitName(str(record, "full_name") ?? "Unknown");
  const telecom: Json[] = [];
  const phone = str(record, "phone");
  const email = str(record, "email");
  if (phone) telecom.push({ system: "phone", value: phone, use: "mobile" });
  if (email) telecom.push({ system: "email", value: email });
  const sex = str(record, "sex")?.toLowerCase() ?? null;
  const gender = sex && ["male", "female", "other", "unknown"].includes(sex) ? sex : null;
  const address = str(record, "address");

  entries.push(
    entry(
      compact({
        resourceType: "Patient",
        identifier: [{ system: "urn:intakeagent:session", value: sessionId }],
        name: [compact({ use: "official", family, given: given.length ? given : null })],
        telecom: telecom.length ? telecom : null,
        gender,
        birthDate: validDate(str(record, "date_of_birth")),
        address: address ? [{ text: address }] : null,
      }),
      patientUrl,
    ),
  );

  const complaint = str(record, "chief_complaint");
  entries.push(
    entry(
      compact({
        resourceType: "Encounter",
        status: "arrived",
        class: {
          system: "http://terminology.hl7.org/CodeSystem/v3-ActCode",
          code: "AMB",
          display: "ambulatory",
        },
        subject: { reference: patientUrl },
        period: { start: now },
        reasonCode: complaint ? [{ text: complaint }] : null,
      }),
      encounterUrl,
    ),
  );

  if (complaint) {
    const severity = str(record, "symptom_severity");
    entries.push(
      entry(
        compact({
          resourceType: "Condition",
          clinicalStatus: { coding: [{ system: CLINICAL, code: "active" }] },
          category: [{ coding: [{ system: CATEGORY, code: "encounter-diagnosis" }] }],
          code: { text: complaint },
          subject: { reference: patientUrl },
          encounter: { reference: encounterUrl },
          onsetString: str(record, "symptom_onset"),
          note: severity ? [{ text: `Severity ${severity}` }] : null,
        }),
        urn(),
      ),
    );
  }

  for (const name of list<string>(record, "conditions")) {
    if (!name) continue;
    entries.push(
      entry(
        {
          resourceType: "Condition",
          clinicalStatus: { coding: [{ system: CLINICAL, code: "active" }] },
          category: [{ coding: [{ system: CATEGORY, code: "problem-list-item" }] }],
          code: { text: String(name) },
          subject: { reference: patientUrl },
        },
        urn(),
      ),
    );
  }

  for (const allergy of list(record, "allergies")) {
    const substance = allergy.substance ? String(allergy.substance) : "";
    const reaction = allergy.reaction ? String(allergy.reaction) : null;
    if (!substance || substance.toLowerCase().startsWith("no known")) continue;
    entries.push(
      entry(
        compact({
          resourceType: "AllergyIntolerance",
          clinicalStatus: {
            coding: [
              {
                system: "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                code: "active",
              },
            ],
          },
          code: { text: substance },
          patient: { reference: patientUrl },
          reaction: reaction ? [{ manifestation: [{ text: reaction }] }] : null,
        }),
        urn(),
      ),
    );
  }

  for (const med of list(record, "medications")) {
    const name = med.name ? String(med.name) : "";
    if (!name || name.toLowerCase().startsWith("none")) continue;
    const dosageText =
      [med.dose, med.frequency].filter((x) => x).map(String).join(" ") || null;
    entries.push(
      entry(
        compact({
          resourceType: "MedicationStatement",
          status: "active",
          medicationCodeableConcept: { text: name },
          subject: { reference: patientUrl },
          context: { reference: encounterUrl },
          dosage: dosageText ? [{ text: dosageText }] : null,
        }),
        urn(),
      ),
    );
  }

  const payer = str(record, "insurance_payer");
  if (payer) {
    entries.push(
      entry(
        compact({
          resourceType: "Coverage",
          status: "active",
          subscriberId: str(record, "insurance_member_id"),
          beneficiary: { reference: patientUrl },
          payor: [{ display: payer }],
        }),
        urn(),
      ),
    );
  }

  return { resourceType: "Bundle", type: "transaction", entry: entries };
}

/** FhirExporter.export() with FHIR_PUSH=0: build the Bundle, never push it. */
export function exportFhir(record: IntakeRecord, sessionId: string): Json {
  const bundle = buildBundle(record, sessionId);
  return {
    target: "fhir",
    mode: "dry-run",
    server: NOT_SENT,
    payload: bundle,
    resource_count: (bundle.entry as unknown[]).length,
  };
}

function clioSplitName(full: string): [string, string] {
  const parts = full.trim().split(/\s+/).filter(Boolean);
  if (parts.length <= 1) return ["", parts[0] ?? ""];
  return [parts.slice(0, -1).join(" "), parts[parts.length - 1] as string];
}

export function buildContactPayload(record: IntakeRecord): Json {
  const [first, last] = clioSplitName(str(record, "client_name") ?? "Unknown Client");
  const data: Json = { type: "Person", first_name: first, last_name: last };
  const phone = str(record, "phone");
  const email = str(record, "email");
  const address = str(record, "address");
  if (phone) data.phone_numbers = [{ name: "Mobile", number: phone, default_number: true }];
  if (email) data.email_addresses = [{ name: "Home", address: email, default_email: true }];
  if (address) data.addresses = [{ name: "Home", street: address }];
  return { data };
}

export function buildMatterPayload(record: IntakeRecord, clientId: number): Json {
  const lines = [str(record, "matter_description") ?? "Intake via IntakeAgent."];
  const opposing = str(record, "opposing_party");
  const jurisdiction = str(record, "jurisdiction");
  const urgency = str(record, "urgency");
  const matterType = str(record, "matter_type");
  if (opposing) lines.push(`Opposing party: ${opposing}`);
  if (jurisdiction) lines.push(`Jurisdiction: ${jurisdiction}`);
  for (const kd of list(record, "key_dates")) {
    lines.push(`Key date: ${String(kd.label ?? "")}: ${String(kd.date ?? "")}`);
  }
  if (urgency) lines.push(`Urgency: ${urgency}`);
  const data: Json = {
    client: { id: clientId },
    description: lines.join("\n"),
    status: "Pending",
    open_date: new Date().toISOString().slice(0, 10),
    billable: true,
  };
  if (matterType) data.practice_area = { name: matterType };
  if (jurisdiction) data.location = jurisdiction;
  return { data };
}

/** Small deterministic string hash (FNV-1a) standing in for Python's hash() in mock ids. */
function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

/** ClioExporter.export() in mock mode: payloads plus a conflict check with zero hits. */
export function exportClio(record: IntakeRecord, sessionId: string): Json {
  const contactPayload = buildContactPayload(record);
  const conflicts = list<string>(record, "conflict_check_names").map((name) => ({
    name,
    hits: [],
    mode: "mock",
  }));
  const contactId = 100000 + (hash(sessionId) % 899999);
  const matterPayload = buildMatterPayload(record, contactId);
  return {
    target: "clio",
    mode: "mock",
    server: NOT_SENT,
    contact: { id: contactId, ...(contactPayload.data as Json) },
    matter: {
      id: contactId + 1,
      display_number: `${new Date().getUTCFullYear()}-${String(contactId % 10000).padStart(5, "0")}`,
      ...(matterPayload.data as Json),
    },
    conflict_check: conflicts,
    payloads: { contact: contactPayload, matter: matterPayload },
  };
}
