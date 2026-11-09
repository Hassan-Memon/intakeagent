"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { previewValue, vertLabel } from "@/lib/format";
import type { ApprovedRecord } from "@/lib/types";
import { StatusPill } from "./StatusPill";

export function RecordsClient() {
  const [records, setRecords] = useState<ApprovedRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listRecords()
      .then(setRecords)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load records"));
  }, []);

  if (error) {
    return (
      <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!records) return <p className="text-sm text-ink-soft">Loading...</p>;
  if (records.length === 0) {
    return (
      <div className="card text-sm text-ink-soft">
        No approved records yet.{" "}
        <Link href="/" className="text-accent underline">
          Start an intake
        </Link>
        .
      </div>
    );
  }

  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full text-sm">
        <thead className="bg-mist text-left text-xs uppercase tracking-wide text-ink-soft">
          <tr>
            <th className="px-4 py-3">Approved</th>
            <th className="px-4 py-3">Type</th>
            <th className="px-4 py-3">Name</th>
            <th className="px-4 py-3">Summary</th>
            <th className="px-4 py-3">Export</th>
            <th className="px-4 py-3" />
          </tr>
        </thead>
        <tbody>
          {records.map((r) => {
            const name = previewValue(r.record.full_name ?? r.record.client_name);
            const summary = previewValue(r.record.chief_complaint ?? r.record.matter_type);
            return (
              <tr key={r.id} className="border-t border-line">
                <td className="whitespace-nowrap px-4 py-3 text-ink-soft">
                  {new Date(r.approved_at).toLocaleString()}
                </td>
                <td className="px-4 py-3">{vertLabel(r.vertical)}</td>
                <td className="px-4 py-3 font-medium">{name || "Unknown"}</td>
                <td className="max-w-xs truncate px-4 py-3 text-ink-soft">{summary}</td>
                <td className="px-4 py-3">
                  {r.export_target ? (
                    <span className="inline-flex items-center gap-2">
                      <StatusPill state="exported" />
                      <span className="text-xs uppercase text-ink-soft">{r.export_target}</span>
                    </span>
                  ) : (
                    <StatusPill state="approved" />
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link href={`/review/${r.session_id}`} className="text-accent underline">
                    Open
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
