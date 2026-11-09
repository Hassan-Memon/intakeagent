"use client";

import { useId, useState } from "react";
import type { Evidence } from "@/lib/types";

/**
 * Small "i" button that reveals the transcript quote a value came from. Hover or focus also
 * reports the span upward so the transcript panel can highlight it.
 */
export function EvidenceTooltip({
  evidence,
  confidence,
  onHover,
}: {
  evidence: Evidence[];
  confidence: number;
  onHover: (span: { start: number; end: number } | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ev = evidence[0];
  if (!ev || !ev.quote) {
    return <span className="text-xs text-ink-soft">no evidence</span>;
  }
  const span = { start: ev.start, end: ev.end };
  return (
    <span className="relative inline-block">
      <button
        type="button"
        aria-label="Show transcript evidence"
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => {
          setOpen(true);
          onHover(span);
        }}
        onMouseLeave={() => {
          setOpen(false);
          onHover(null);
        }}
        onFocus={() => {
          setOpen(true);
          onHover(span);
        }}
        onBlur={() => {
          setOpen(false);
          onHover(null);
        }}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-line text-[11px] font-bold text-ink-soft hover:border-accent hover:text-accent"
      >
        i
      </button>
      {open && (
        <span
          role="tooltip"
          id={id}
          className="absolute right-0 top-7 z-20 w-72 rounded-xl border border-line bg-white p-3 text-left text-xs shadow-lg"
        >
          <span className="block font-semibold text-ink-soft">From the transcript</span>
          <span className="mt-1 block italic text-ink">&ldquo;{ev.quote}&rdquo;</span>
          <span className="mt-2 block text-ink-soft">
            confidence {Math.round(confidence * 100)}%
          </span>
        </span>
      )}
    </span>
  );
}
