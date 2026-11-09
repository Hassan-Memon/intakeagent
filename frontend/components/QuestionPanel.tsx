"use client";

import { labelFor } from "@/lib/format";
import type { FieldSpec } from "@/lib/types";

/** The agent's current question plus a checklist of required fields. */
export function QuestionPanel({
  question,
  field,
  specs,
  missing,
  busy,
}: {
  question: string | null;
  field: string | null;
  specs: FieldSpec[];
  missing: string[];
  busy: boolean;
}) {
  const required = specs.filter((s) => s.required);
  const done = required.filter((s) => !missing.includes(s.name)).length;

  return (
    <div className="space-y-5">
      <div
        className="rounded-2xl bg-accent-soft p-5"
        aria-live="polite"
        aria-atomic="true"
      >
        <p className="label text-accent-strong">Assistant</p>
        <p className="mt-2 text-lg leading-snug text-ink">
          {busy ? "One moment..." : question ?? "Ready when you are."}
        </p>
        {field && !busy && (
          <p className="mt-2 text-xs text-ink-soft">Listening for: {labelFor(field)}</p>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between">
          <p className="label">Required details</p>
          <p className="text-xs text-ink-soft">
            {done} of {required.length}
          </p>
        </div>
        <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-line">
          <div
            className="h-full bg-accent transition-all"
            style={{ width: `${required.length ? (done / required.length) * 100 : 0}%` }}
          />
        </div>
        <ul className="mt-3 grid grid-cols-1 gap-1.5 text-sm sm:grid-cols-2">
          {required.map((s) => {
            const captured = !missing.includes(s.name);
            return (
              <li key={s.name} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] ${
                    captured ? "bg-ok text-white" : "border border-line text-transparent"
                  }`}
                >
                  ✓
                </span>
                <span className={captured ? "text-ink" : "text-ink-soft"}>
                  {labelFor(s.name)}
                  <span className="sr-only">{captured ? " captured" : " missing"}</span>
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
