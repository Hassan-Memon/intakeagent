"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Vertical } from "@/lib/types";

const OPTIONS: { vertical: Vertical; title: string; body: string; output: string }[] = [
  {
    vertical: "healthcare",
    title: "Clinic patient intake",
    body: "Demographics, reason for visit, medications, allergies and insurance.",
    output: "Exports a FHIR R4 Bundle (Patient, Encounter, Condition, AllergyIntolerance, MedicationStatement).",
  },
  {
    vertical: "legal",
    title: "Law firm client intake",
    body: "Client details, matter type, opposing party, key dates and conflict-check names.",
    output: "Exports a Clio Contact and Matter (API v4) after a conflict check.",
  },
];

export function StartIntake() {
  const router = useRouter();
  const [busy, setBusy] = useState<Vertical | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<{ demo_mode: boolean; llm: string; stt: string } | null>(
    null,
  );

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  async function start(vertical: Vertical) {
    setBusy(vertical);
    setError(null);
    try {
      const session = await api.createSession(vertical);
      router.push(`/intake/${session.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the backend.");
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        {OPTIONS.map((opt) => (
          <button
            key={opt.vertical}
            type="button"
            onClick={() => start(opt.vertical)}
            disabled={busy !== null}
            className="card text-left transition hover:border-accent hover:shadow-md disabled:opacity-60"
          >
            <h2 className="text-xl font-semibold">{opt.title}</h2>
            <p className="mt-2 text-sm text-ink-soft">{opt.body}</p>
            <p className="mt-4 text-xs text-ink-soft">{opt.output}</p>
            <span className="mt-5 inline-block text-sm font-semibold text-accent">
              {busy === opt.vertical ? "Starting..." : "Start intake"}
            </span>
          </button>
        ))}
      </div>
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-danger">
          {error}. Is the backend running on {process.env.NEXT_PUBLIC_API_URL ?? "localhost:8000"}?
        </p>
      )}
      {health && (
        <p className="text-xs text-ink-soft">
          Backend: {health.demo_mode ? "demo mode (scripted speech, no keys needed)" : "live"}; LLM{" "}
          {health.llm}; speech-to-text {health.stt}.
        </p>
      )}
    </div>
  );
}
