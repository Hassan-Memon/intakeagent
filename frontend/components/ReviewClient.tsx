"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DEMO_MODE, api } from "@/lib/api";
import { codesOf, emptyCodes, withCodes, withoutCodes } from "@/lib/codes";
import { vertLabel } from "@/lib/format";
import type { IntakeRecord, ReviewerCodes, Session, Verification } from "@/lib/types";
import { RecordForm } from "./RecordForm";
import { StatusPill } from "./StatusPill";
import { TranscriptPanel } from "./TranscriptPanel";
import { VerificationPanel } from "./VerificationPanel";

/** Confident RxNorm matches start ticked; ICD-10 codes are always the reviewer's pick. */
function preselectCodes(v: Verification, current: ReviewerCodes): ReviewerCodes {
  const next = { ...current, medications: { ...current.medications }, allergies: { ...current.allergies } };
  for (const c of v.medications ?? []) {
    if (c.match && (c.confidence ?? 0) >= 0.9 && !(c.input in next.medications)) {
      next.medications[c.input] = c.match;
    }
  }
  for (const c of v.allergies ?? []) {
    if (c.match && (c.confidence ?? 0) >= 0.9 && !(c.input in next.allergies)) {
      next.allergies[c.input] = c.match;
    }
  }
  return next;
}

const recordKey = (r: IntakeRecord) => JSON.stringify(withoutCodes(r));

export function ReviewClient({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<Session | null>(null);
  const [record, setRecord] = useState<IntakeRecord>({});
  const [highlight, setHighlight] = useState<{ start: number; end: number } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<Record<string, unknown> | null>(null);
  const [codes, setCodes] = useState<ReviewerCodes>(emptyCodes());
  const [verification, setVerification] = useState<Verification | null>(null);
  const [checkedKey, setCheckedKey] = useState<string>("");
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const runChecks = useCallback(
    async (id: string, edited: IntakeRecord | undefined, preselect: boolean) => {
      setVerifyBusy(true);
      setVerifyError(null);
      try {
        const v = await api.verify(id, edited);
        setVerification(v);
        setCheckedKey(edited ? recordKey(edited) : "");
        setAcknowledged(false);
        if (preselect) setCodes((c) => preselectCodes(v, c));
      } catch (e) {
        setVerifyError(e instanceof Error ? e.message : "Checks failed");
      } finally {
        setVerifyBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    api
      .getSession(sessionId)
      .then((s) => {
        setSession(s);
        setRecord(s.record);
        const existing = codesOf(s.record);
        setCodes(existing);
        if (Object.keys(s.record).length) {
          const done = s.status === "approved" || s.status === "exported";
          void runChecks(s.id, s.record, !done);
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Session not found"));
  }, [sessionId, runChecks]);

  // Recompute "missing" locally as the reviewer edits, so the badges update live.
  const missing = useMemo(() => {
    if (!session) return [];
    return session.field_specs
      .filter((s) => s.required)
      .filter((s) => {
        const v = record[s.name]?.value;
        if (v === null || v === undefined) return true;
        if (typeof v === "string") return v.trim() === "";
        if (Array.isArray(v)) return v.length === 0;
        return false;
      })
      .map((s) => s.name);
  }, [session, record]);

  const approved = session?.status === "approved" || session?.status === "exported";
  const exportTarget = session?.vertical === "healthcare" ? "fhir" : "clio";

  function onChange(name: string, value: unknown) {
    setRecord((prev) => {
      const current = prev[name] ?? { value: null, evidence: [], confidence: 0 };
      return { ...prev, [name]: { ...current, value, confidence: current.confidence || 1 } };
    });
  }

  const flags = verification?.flags ?? [];
  const stale = Boolean(verification) && checkedKey !== "" && checkedKey !== recordKey(record);
  const needsAck = flags.length > 0 && !acknowledged;

  async function approve() {
    if (!session || needsAck) return;
    setBusy("approve");
    setError(null);
    try {
      const toSend = session.vertical === "healthcare" ? withCodes(record, codes) : record;
      await api.approve(session.id, toSend, undefined, flags.map((f) => f.id));
      const fresh = await api.getSession(session.id);
      setSession(fresh);
      setRecord(fresh.record);
      setCodes(codesOf(fresh.record));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setBusy(null);
    }
  }

  async function doExport() {
    if (!session) return;
    setBusy("export");
    setError(null);
    try {
      const result = await api.exportSession(session.id, exportTarget);
      setExportResult(result);
      setSession(await api.getSession(session.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusy(null);
    }
  }

  function downloadExport() {
    if (!session || !exportResult) return;
    // FHIR: the transaction Bundle itself, ready to POST to a FHIR server. Clio: the full
    // result (contact, matter, conflict check and the exact v4 request payloads).
    const body = exportTarget === "fhir" ? exportResult.payload : exportResult;
    const name =
      exportTarget === "fhir"
        ? `fhir-bundle-${session.id.slice(0, 8)}.json`
        : `clio-contact-matter-${session.id.slice(0, 8)}.json`;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  if (error && !session) {
    return (
      <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!session) return <p className="text-sm text-ink-soft">Loading...</p>;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="label">{vertLabel(session.vertical)} intake</p>
          <h1 className="text-2xl font-bold tracking-tight">Review and approve</h1>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill state={session.status} />
          {session.status === "recording" && (
            <Link href={`/intake/${session.id}`} className="text-sm text-accent underline">
              Back to live intake
            </Link>
          )}
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          <VerificationPanel
            verification={verification}
            codes={codes}
            onCodesChange={setCodes}
            readOnly={approved}
            busy={verifyBusy}
            stale={stale}
            error={verifyError}
            onRerun={() => void runChecks(session.id, record, true)}
          />
          <section className="card">
            <p className="mb-4 text-sm text-ink-soft">
              Hover the <span className="font-semibold">i</span> next to a field to see the transcript
              it came from. Edit anything that is wrong, then approve.
            </p>
            <RecordForm
              specs={session.field_specs}
              record={record}
              missing={missing}
              readOnly={approved}
              onChange={onChange}
              onHoverEvidence={setHighlight}
            />
          </section>
        </div>

        <aside className="space-y-6 lg:col-span-2">
          <div className="card space-y-3">
            <p className="label">Actions</p>
            {!approved ? (
              <>
                {flags.length > 0 && (
                  <label className="flex items-start gap-2 rounded-xl bg-warn-soft px-3 py-2 text-sm text-warn">
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 accent-warn"
                      checked={acknowledged}
                      onChange={(e) => setAcknowledged(e.target.checked)}
                    />
                    <span>
                      I have reviewed the {flags.length} flag{flags.length === 1 ? "" : "s"} from the
                      reference checks. (Recorded in the audit trail.)
                    </span>
                  </label>
                )}
                <button
                  type="button"
                  onClick={approve}
                  disabled={busy !== null || needsAck}
                  className="btn-primary w-full"
                >
                  {busy === "approve" ? "Approving..." : "Approve record"}
                </button>
                <p className="text-xs text-ink-soft">
                  {missing.length > 0
                    ? `${missing.length} required field${missing.length === 1 ? "" : "s"} still empty. You can approve anyway; they will be exported as blank.`
                    : "All required fields are present."}
                </p>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={doExport}
                  disabled={busy !== null}
                  className="btn-primary w-full"
                >
                  {busy === "export"
                    ? "Exporting..."
                    : exportTarget === "fhir"
                      ? "Export FHIR R4 Bundle"
                      : "Export to Clio (Contact + Matter)"}
                </button>
                <p className="text-xs text-ink-soft">
                  {DEMO_MODE
                    ? "Approved. In this demo the payload is built in your browser and is not sent anywhere."
                    : exportTarget === "fhir"
                      ? "Approved. Export builds the payload and pushes to the FHIR server only if FHIR_PUSH=1."
                      : "Approved. Export builds the payload and runs a conflict check; live mode needs Clio OAuth credentials."}
                </p>
              </>
            )}
            <Link href="/records" className="btn-secondary w-full">
              View all records
            </Link>
          </div>

          {exportResult && (
            <div className="card">
              <p className="label">Export result</p>
              <p className="mt-1 text-sm">
                Mode: <span className="font-semibold">{String(exportResult.mode ?? "")}</span>
                {"resource_count" in exportResult && (
                  <> &middot; {String(exportResult.resource_count)} FHIR resources</>
                )}
                {"conflict_check" in exportResult && (
                  <>
                    {" "}
                    &middot; conflict check on{" "}
                    {(exportResult.conflict_check as unknown[]).length} names
                  </>
                )}
              </p>
              <button type="button" onClick={downloadExport} className="btn-secondary mt-3 w-full">
                Download {exportTarget === "fhir" ? "FHIR Bundle" : "Clio JSON"} (.json)
              </button>
              <details className="mt-3" open={DEMO_MODE}>
                <summary className="cursor-pointer text-sm text-accent">Show payload</summary>
                <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-mist p-3 text-[11px] leading-snug">
                  {JSON.stringify(exportResult, null, 2)}
                </pre>
              </details>
            </div>
          )}

          <div className="card">
            <p className="label">Transcript</p>
            <div className="mt-2 max-h-96 overflow-y-auto">
              <TranscriptPanel
                segments={session.transcript_segments}
                highlight={highlight}
                autoScroll={false}
              />
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
