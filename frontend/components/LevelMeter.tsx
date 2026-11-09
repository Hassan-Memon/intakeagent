"use client";

/** Twelve-bar input level meter driven by the recorder's RMS value (0..1). */
export function LevelMeter({ level, active }: { level: number; active: boolean }) {
  const bars = 12;
  const lit = Math.round(level * bars);
  return (
    <div
      role="meter"
      aria-label="Microphone input level"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(level * 100)}
      className="flex h-8 items-end gap-1"
    >
      {Array.from({ length: bars }, (_, i) => {
        const on = active && i < lit;
        const height = 8 + (i / bars) * 24;
        return (
          <span
            key={i}
            style={{ height }}
            className={`w-2 rounded-sm transition-colors ${
              on ? (i > bars - 3 ? "bg-warn" : "bg-accent") : "bg-line"
            }`}
          />
        );
      })}
    </div>
  );
}
