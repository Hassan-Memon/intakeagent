"use client";

import type {
  Coding,
  DrugCheck,
  IcdCheck,
  ReviewerCodes,
  SanctionsResult,
  Verification,
  VerificationFlag,
} from "@/lib/types";

const MODE_LABEL: Record<string, string> = {
  live: "live",
  offline: "bundled snapshot",
  local: "local copy",
  demo: "fictional demo list",
};

const SANCTION_STYLE: Record<SanctionsResult["status"], string> = {
  clear: "bg-ok-soft text-ok",
  possible_match: "bg-warn-soft text-warn",
  strong_match: "bg-red-50 text-danger",
};

function FlagItem({ flag }: { flag: VerificationFlag }) {
  const high = flag.severity === "high";
  return (
    <li
      className={`rounded-xl border px-3 py-2.5 ${
        high ? "border-danger/30 bg-red-50" : "border-warn/30 bg-warn-soft"
      }`}
    >
      <p className={`text-sm font-semibold ${high ? "text-danger" : "text-warn"}`}>
        <span aria-hidden="true">{high ? "⛔ " : "⚠ "}</span>
        {flag.title}
      </p>
      <p className="mt-1 text-xs leading-relaxed text-ink">{flag.detail}</p>
    </li>
  );
}

function CodeBadge({ coding, prefix }: { coding: Coding; prefix: string }) {
  return (
    <span className="whitespace-nowrap rounded-md bg-mist px-1.5 py-0.5 font-mono text-[11px] text-ink">
      {prefix} {coding.code}
    </span>
  );
}

function DrugRows({
  title,
  checks,
  accepted,
  readOnly,
  onToggle,
}: {
  title: string;
  checks: DrugCheck[];
  accepted: Record<string, Coding>;
  readOnly: boolean;
  onToggle: (input: string, coding: Coding | null) => void;
}) {
  if (!checks.length) return null;
  return (
    <div>
      <p className="mb-1.5 text-sm font-semibold">{title}</p>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {checks.map((c) => {
          const id = `code-${title}-${c.input}`.replace(/\W+/g, "-");
          return (
            <li key={c.input} className="flex items-start gap-3 px-3 py-2">
              {c.match ? (
                <input
                  id={id}
                  type="checkbox"
                  className="mt-1 h-4 w-4 accent-accent"
                  checked={Boolean(accepted[c.input])}
                  disabled={readOnly}
                  onChange={(e) => onToggle(c.input, e.target.checked ? c.match : null)}
                />
              ) : (
                <span className="mt-1 inline-block h-4 w-4" aria-hidden="true" />
              )}
              <label htmlFor={c.match ? id : undefined} className="min-w-0 flex-1 text-sm">
                <span className="font-medium">{c.input}</span>
                {c.match ? (
                  <>
                    {" "}
                    <span className="text-ink-soft">&rarr; {c.match.display}</span>{" "}
                    <CodeBadge coding={c.match} prefix="RxNorm" />
                    {typeof c.confidence === "number" && c.confidence < 0.8 && (
                      <span className="ml-1 text-[11px] font-semibold text-warn">
                        weak match, check
                      </span>
                    )}
                    {c.classes && c.classes.length > 0 && (
                      <span className="block truncate text-xs text-ink-soft">
                        {c.classes.join(" · ")}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="block text-xs text-ink-soft">
                    {c.status === "drug_class"
                      ? "Drug class: checked against medication classes, not coded as a product"
                      : c.status === "not_a_drug"
                        ? "Not a medication: no RxNorm code"
                        : c.status === "error"
                          ? "Lookup failed; left as text"
                          : "No RxNorm match; exported as text"}
                  </span>
                )}
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function IcdPicker({
  title,
  check,
  accepted,
  readOnly,
  onPick,
}: {
  title: string;
  check: IcdCheck;
  accepted: Record<string, Coding>;
  readOnly: boolean;
  onPick: (input: string, coding: Coding | null) => void;
}) {
  const name = `icd-${title}-${check.input}`.replace(/\W+/g, "-");
  const chosen = accepted[check.input]?.code ?? "";
  return (
    <fieldset className="rounded-xl border border-line px-3 py-2">
      <legend className="px-1 text-sm font-semibold">{title}</legend>
      <p className="text-xs text-ink-soft">
        &ldquo;{check.input}&rdquo;{" "}
        {check.query && check.query !== check.input.toLowerCase() && (
          <>searched as &ldquo;{check.query}&rdquo;</>
        )}
      </p>
      {check.suggestions.length === 0 ? (
        <p className="mt-1 text-xs text-ink-soft">No ICD-10-CM suggestion; exported as text.</p>
      ) : (
        <div className="mt-1.5 space-y-1">
          {check.suggestions.map((s) => (
            <label key={s.code} className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name={name}
                className="mt-1 accent-accent"
                checked={chosen === s.code}
                disabled={readOnly}
                onChange={() => onPick(check.input, s)}
              />
              <span>
                <CodeBadge coding={s} prefix="ICD-10" /> {s.display}
              </span>
            </label>
          ))}
          <label className="flex items-center gap-2 text-sm text-ink-soft">
            <input
              type="radio"
              name={name}
              className="accent-accent"
              checked={chosen === ""}
              disabled={readOnly}
              onChange={() => onPick(check.input, null)}
            />
            No code (export the patient&apos;s words only)
          </label>
        </div>
      )}
    </fieldset>
  );
}

function SanctionsTable({ verification }: { verification: Verification }) {
  const s = verification.sanctions;
  if (!s) return null;
  if (s.status !== "ok" || !s.list) {
    return (
      <p className="rounded-xl bg-warn-soft px-3 py-2 text-sm text-warn">
        Sanctions screening did not run: {s.message ?? "no list loaded"}
      </p>
    );
  }
  return (
    <div>
      <p className="mb-1.5 text-xs text-ink-soft">
        {s.results.length} name{s.results.length === 1 ? "" : "s"} screened against{" "}
        <span className="font-semibold">{s.list.name}</span> ({s.list.entry_count.toLocaleString()}{" "}
        entries, as of {s.list.generated_at.slice(0, 10)}). Matching ran locally; no name was sent
        anywhere.
      </p>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {s.results.map((r) => (
          <li key={r.name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
            <div className="min-w-0">
              <p className="text-sm font-medium">{r.name}</p>
              <p className="text-xs text-ink-soft">
                {r.role}
                {r.matches[0] && (
                  <>
                    {" "}
                    &middot; closest: {r.matches[0].matched_name} ({r.matches[0].list},{" "}
                    {r.matches[0].score.toFixed(2)})
                  </>
                )}
              </p>
            </div>
            <span
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${SANCTION_STYLE[r.status]}`}
            >
              {r.status.replace("_", " ")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function VerificationPanel({
  verification,
  codes,
  onCodesChange,
  readOnly,
  busy,
  stale,
  error,
  onRerun,
}: {
  verification: Verification | null;
  codes: ReviewerCodes;
  onCodesChange: (codes: ReviewerCodes) => void;
  readOnly: boolean;
  busy: boolean;
  stale: boolean;
  error: string | null;
  onRerun: () => void;
}) {
  function setCode(group: keyof ReviewerCodes, input: string, coding: Coding | null) {
    const next = { ...codes[group] };
    if (coding) next[input] = coding;
    else delete next[input];
    onCodesChange({ ...codes, [group]: next });
  }

  const healthcare = verification?.vertical === "healthcare";

  return (
    <section className="card space-y-4" aria-labelledby="checks-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="checks-title" className="text-base font-semibold">
            Reference checks
          </h2>
          <p className="text-xs text-ink-soft">
            {healthcare
              ? "Medications and allergies checked against RxNorm, complaint and conditions against ICD-10-CM."
              : "Every party screened against public sanctions lists before the matter is opened."}
          </p>
        </div>
        {!readOnly && (
          <button type="button" onClick={onRerun} disabled={busy} className="btn-secondary !py-1.5">
            {busy ? "Checking..." : "Re-run checks"}
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      {!verification && !error && <p className="text-sm text-ink-soft">Running checks...</p>}

      {verification && (
        <>
          {stale && !readOnly && (
            <p className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
              The record changed since these checks ran. Re-run them before approving.
            </p>
          )}

          {verification.flags.length > 0 ? (
            <ul className="space-y-2" aria-label="Flags">
              {verification.flags.map((f) => (
                <FlagItem key={f.id} flag={f} />
              ))}
            </ul>
          ) : (
            <p className="rounded-xl bg-ok-soft px-3 py-2 text-sm text-ok">
              {healthcare
                ? "No medication matches a reported allergy."
                : "No party resembles a listed name."}
            </p>
          )}

          {healthcare && (
            <div className="space-y-4">
              <DrugRows
                title="Medications"
                checks={verification.medications ?? []}
                accepted={codes.medications}
                readOnly={readOnly}
                onToggle={(i, c) => setCode("medications", i, c)}
              />
              <DrugRows
                title="Allergies"
                checks={verification.allergies ?? []}
                accepted={codes.allergies}
                readOnly={readOnly}
                onToggle={(i, c) => setCode("allergies", i, c)}
              />
              {verification.chief_complaint && (
                <IcdPicker
                  title="Chief complaint"
                  check={verification.chief_complaint}
                  accepted={codes.chief_complaint}
                  readOnly={readOnly}
                  onPick={(i, c) => setCode("chief_complaint", i, c)}
                />
              )}
              {(verification.conditions ?? []).map((c) => (
                <IcdPicker
                  key={c.input}
                  title="Condition"
                  check={c}
                  accepted={codes.conditions}
                  readOnly={readOnly}
                  onPick={(i, coding) => setCode("conditions", i, coding)}
                />
              ))}
              <p className="text-xs text-ink-soft">
                Ticked codes are added to the FHIR export next to the patient&apos;s own words.
                Confident drug matches start ticked; diagnosis codes are never picked for you.
              </p>
            </div>
          )}

          {!healthcare && <SanctionsTable verification={verification} />}

          {(verification.errors ?? []).length > 0 && (
            <ul className="space-y-1 text-xs text-warn">
              {(verification.errors ?? []).map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}

          <p className="border-t border-line pt-3 text-[11px] leading-relaxed text-ink-soft">
            Sources:{" "}
            {verification.sources
              .map((s) => `${s.name} (${MODE_LABEL[s.mode] ?? s.mode})`)
              .join("; ") || "none"}
            . Reference data to speed up review, not clinical or legal advice. Nothing changes
            in the record unless you accept it.
          </p>
        </>
      )}
    </section>
  );
}
