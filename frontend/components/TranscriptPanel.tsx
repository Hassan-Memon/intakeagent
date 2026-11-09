"use client";

import { useEffect, useRef } from "react";
import { formatMs } from "@/lib/format";
import type { TranscriptSegment } from "@/lib/types";

/**
 * Live transcript. When `highlight` is set (char offsets into the merged transcript) the
 * matching span is wrapped in <mark> so reviewers can see where a value came from.
 */
export function TranscriptPanel({
  segments,
  highlight,
  autoScroll = true,
}: {
  segments: TranscriptSegment[];
  highlight?: { start: number; end: number } | null;
  autoScroll?: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (autoScroll) endRef.current?.scrollIntoView({ block: "nearest" });
  }, [segments.length, autoScroll]);

  // Recompute char offsets the same way the backend does: segments joined by one space.
  let offset = 0;
  const rows = segments.map((seg) => {
    const start = offset;
    offset += seg.text.trim().length + 1;
    return { seg, start };
  });

  if (segments.length === 0) {
    return (
      <p className="text-sm text-ink-soft">
        Nothing yet. Press the microphone and start talking, or type below.
      </p>
    );
  }

  return (
    <ol className="space-y-3" aria-label="Transcript">
      {rows.map(({ seg, start }) => (
        <li key={seg.id} className="flex gap-3 text-sm leading-relaxed">
          <span className="w-10 shrink-0 pt-0.5 font-mono text-xs text-ink-soft">
            {formatMs(seg.start_ms)}
          </span>
          <p>{renderWithHighlight(seg.text.trim(), start, highlight)}</p>
        </li>
      ))}
      <div ref={endRef} />
    </ol>
  );
}

function renderWithHighlight(
  text: string,
  segStart: number,
  highlight?: { start: number; end: number } | null,
) {
  if (!highlight || highlight.start < 0) return text;
  const s = Math.max(0, highlight.start - segStart);
  const e = Math.min(text.length, highlight.end - segStart);
  if (e <= 0 || s >= text.length) return text;
  return (
    <>
      {text.slice(0, s)}
      <mark className="evidence">{text.slice(s, e)}</mark>
      {text.slice(e)}
    </>
  );
}
