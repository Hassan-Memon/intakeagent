import { demoApi } from "./demo/backend";
import type { ApprovedRecord, IntakeRecord, Session, Verification, Vertical } from "./types";

/**
 * NEXT_PUBLIC_DEMO_MODE=1 swaps the HTTP client for an in-browser simulation of the backend
 * (lib/demo). Used for the public static demo; nothing leaves the page in that mode.
 */
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "1";

// Default to 127.0.0.1 rather than localhost: browsers may resolve localhost to ::1 while
// the backend listens on IPv4 only, which shows up as a misleading CORS error.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
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

const httpApi = {
  createSession: (vertical: Vertical) =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify({ vertical }) }),
  getSession: (id: string) => request<Session>(`/sessions/${id}`),
  approve: (
    id: string,
    record: IntakeRecord,
    exportTarget?: "fhir" | "clio",
    acknowledgedFlags?: string[],
  ) =>
    request<{ status: string; record: ApprovedRecord }>(`/sessions/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({
        record,
        export_target: exportTarget ?? null,
        acknowledged_flags: acknowledgedFlags ?? [],
      }),
    }),
  /** Reference-data checks on the stored record, or on the reviewer's edited copy. */
  verify: (id: string, record?: IntakeRecord) =>
    request<Verification>(`/sessions/${id}/verify`, {
      method: "POST",
      body: JSON.stringify({ record: record ?? null }),
    }),
  exportSession: (id: string, target: "fhir" | "clio") =>
    request<Record<string, unknown>>(`/sessions/${id}/export?target=${target}`, {
      method: "POST",
    }),
  listRecords: () => request<ApprovedRecord[]>("/records"),
  health: () =>
    request<{ demo_mode: boolean; llm: string; stt: string; llm_local: boolean }>("/health"),
};

// The env check is spelled out (not DEMO_MODE) so the minifier can fold it and drop the demo
// module from normal builds.
export const api: typeof httpApi =
  process.env.NEXT_PUBLIC_DEMO_MODE === "1" ? demoApi : httpApi;
