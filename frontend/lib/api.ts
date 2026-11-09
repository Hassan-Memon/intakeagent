import type { ApprovedRecord, IntakeRecord, Session, Vertical } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? API_URL.replace(/^http/, "ws");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // keep statusText
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

export const api = {
  createSession: (vertical: Vertical) =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify({ vertical }) }),
  getSession: (id: string) => request<Session>(`/sessions/${id}`),
  approve: (id: string, record: IntakeRecord, exportTarget?: "fhir" | "clio") =>
    request<{ status: string; record: ApprovedRecord }>(`/sessions/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ record, export_target: exportTarget ?? null }),
    }),
  exportSession: (id: string, target: "fhir" | "clio") =>
    request<Record<string, unknown>>(`/sessions/${id}/export?target=${target}`, {
      method: "POST",
    }),
  listRecords: () => request<ApprovedRecord[]>("/records"),
  health: () =>
    request<{ demo_mode: boolean; llm: string; stt: string; llm_local: boolean }>("/health"),
};
