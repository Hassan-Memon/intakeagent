"use client";

import { labelFor } from "@/lib/format";
import type { Extracted, FieldSpec, IntakeRecord } from "@/lib/types";
import { EvidenceTooltip } from "./EvidenceTooltip";

// Column layout for list-of-object fields. Anything else falls back to one string per line.
const OBJECT_COLUMNS: Record<string, string[]> = {
  medications: ["name", "dose", "frequency"],
  allergies: ["substance", "reaction"],
  key_dates: ["label", "date"],
};

const GROUP_TITLES: Record<string, string> = {
  demographics: "Patient details",
  visit: "Reason for visit",
  history: "History",
  insurance: "Insurance",
  client: "Client details",
  matter: "Matter",
  conflicts: "Conflict check",
  general: "Details",
};

export function RecordForm({
  specs,
  record,
  missing,
  readOnly,
  onChange,
  onHoverEvidence,
}: {
  specs: FieldSpec[];
  record: IntakeRecord;
  missing: string[];
  readOnly: boolean;
  onChange: (name: string, value: unknown) => void;
  onHoverEvidence: (span: { start: number; end: number } | null) => void;
}) {
  const groups = Array.from(new Set(specs.map((s) => s.group)));

  return (
    <div className="space-y-8">
      {groups.map((group) => (
        <fieldset key={group} className="space-y-4">
          <legend className="text-base font-semibold">{GROUP_TITLES[group] ?? labelFor(group)}</legend>
          {specs
            .filter((s) => s.group === group)
            .map((spec) => {
              const field: Extracted = record[spec.name] ?? { value: null, evidence: [], confidence: 0 };
              const isMissing = spec.required && missing.includes(spec.name);
              return (
                <div key={spec.name} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-3">
                    <label htmlFor={`f-${spec.name}`} className="text-sm font-medium">
                      {labelFor(spec.name)}
                      {spec.required && (
                        <span className="ml-1 text-danger" aria-hidden="true">
                          *
                        </span>
                      )}
                      {spec.required && <span className="sr-only"> (required)</span>}
                    </label>
                    <div className="flex items-center gap-2">
                      {isMissing && (
                        <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn">
                          missing
                        </span>
                      )}
                      <EvidenceTooltip
                        evidence={field.evidence}
                        confidence={field.confidence}
                        onHover={onHoverEvidence}
                      />
                    </div>
                  </div>
                  {spec.kind === "list" ? (
                    <ListEditor
                      id={`f-${spec.name}`}
                      name={spec.name}
                      value={field.value}
                      readOnly={readOnly}
                      onChange={(v) => onChange(spec.name, v)}
                    />
                  ) : (
                    <input
                      id={`f-${spec.name}`}
                      className={`input ${isMissing ? "border-warn" : ""}`}
                      value={field.value === null || field.value === undefined ? "" : String(field.value)}
                      readOnly={readOnly}
                      placeholder={spec.question}
                      onChange={(e) => onChange(spec.name, e.target.value)}
                    />
                  )}
                  {spec.description && <p className="text-xs text-ink-soft">{spec.description}</p>}
                </div>
              );
            })}
        </fieldset>
      ))}
    </div>
  );
}

function ListEditor({
  id,
  name,
  value,
  readOnly,
  onChange,
}: {
  id: string;
  name: string;
  value: unknown;
  readOnly: boolean;
  onChange: (v: unknown) => void;
}) {
  const columns = OBJECT_COLUMNS[name];
  const items = Array.isArray(value) ? value : [];

  if (!columns) {
    // list of strings: one per line
    const text = items.map((x) => String(x)).join("\n");
    return (
      <textarea
        id={id}
        className="input min-h-20"
        value={text}
        readOnly={readOnly}
        placeholder="One per line"
        onChange={(e) =>
          onChange(
            e.target.value
              .split("\n")
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
      />
    );
  }

  const rows = items as Record<string, string | null>[];
  const update = (idx: number, col: string, v: string) => {
    const next = rows.map((r, i) => (i === idx ? { ...r, [col]: v || null } : r));
    onChange(next);
  };
  const add = () => onChange([...rows, Object.fromEntries(columns.map((c) => [c, null]))]);
  const remove = (idx: number) => onChange(rows.filter((_, i) => i !== idx));

  return (
    <div className="space-y-2" id={id}>
      {rows.length === 0 && <p className="text-xs text-ink-soft">None recorded.</p>}
      {rows.map((row, idx) => (
        <div key={idx} className="flex flex-wrap items-center gap-2">
          {columns.map((col) => (
            <input
              key={col}
              aria-label={`${labelFor(name)} ${idx + 1} ${col}`}
              className="input min-w-28 flex-1"
              placeholder={col}
              value={row[col] ?? ""}
              readOnly={readOnly}
              onChange={(e) => update(idx, col, e.target.value)}
            />
          ))}
          {!readOnly && (
            <button
              type="button"
              onClick={() => remove(idx)}
              className="btn-secondary px-3 py-2 text-xs"
              aria-label={`Remove ${labelFor(name)} ${idx + 1}`}
            >
              Remove
            </button>
          )}
        </div>
      ))}
      {!readOnly && (
        <button type="button" onClick={add} className="btn-secondary px-3 py-1.5 text-xs">
          Add {labelFor(name).toLowerCase().replace(/ies$/, "y").replace(/s$/, "")}
        </button>
      )}
    </div>
  );
}
