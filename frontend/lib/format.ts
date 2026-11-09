import type { Extracted } from "./types";

export function labelFor(name: string): string {
  return name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function formatMs(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Human-readable preview of an Extracted value for tables and summaries. */
export function previewValue(field: Extracted | undefined): string {
  if (!field || field.value === null || field.value === undefined) return "";
  const v = field.value;
  if (Array.isArray(v)) {
    return v
      .map((item) => {
        if (item && typeof item === "object") {
          return Object.values(item as Record<string, unknown>)
            .filter((x) => x !== null && x !== undefined && x !== "")
            .join(" ");
        }
        return String(item);
      })
      .join(", ");
  }
  return String(v);
}

export function vertLabel(v: string): string {
  return v === "healthcare" ? "Clinic" : "Law firm";
}
