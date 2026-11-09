"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { vertLabel } from "@/lib/format";
import type { IntakeRecord, Session } from "@/lib/types";
import { RecordForm } from "./RecordForm";
import { StatusPill } from "./StatusPill";
import { TranscriptPanel } from "./TranscriptPanel";

export function ReviewClient({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<Session | null>(null);
  const [record, setRecord] = useState<IntakeRecord>({});
  const [highlight, setHighlight] = useState<{ start: number; end: number } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    api
      .getSession(sessionId)
      .then((s) => {
        setSession(s);
        setRecord(s.record);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Session not found"));
  }, [sessionId]);

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

  async function approve() {
    if (!session) return;
    setBusy("approve");
    setError(null);
    try {
      await api.approve(session.id, record);
      const fresh = await api.getSession(session.id);
      setSession(fresh);
      setRecord(fresh.record);
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
        <section className="card lg:col-span-3">
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

        <aside className="space-y-6 lg:col-span-2">
          <div className="card space-y-3">
            <p className="label">Actions</p>
            {!approved ? (
              <>
                <button
                  type="button"
                  onClick={approve}
                  disabled={busy !== null}
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
                  Approved. Export builds the payload{" "}
                  {exportTarget === "fhir"
                    ? "and pushes to the FHIR server only if FHIR_PUSH=1."
                    : "and runs a conflict check; live mode needs Clio OAuth credentials."}
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
              <details className="mt-3">
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
