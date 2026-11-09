const STYLES: Record<string, string> = {
  recording: "bg-accent-soft text-accent-strong",
  listening: "bg-accent-soft text-accent-strong",
  transcribing: "bg-warn-soft text-warn",
  thinking: "bg-warn-soft text-warn",
  finishing: "bg-warn-soft text-warn",
  awaiting_approval: "bg-warn-soft text-warn",
  approved: "bg-ok-soft text-ok",
  exported: "bg-ok-soft text-ok",
  disconnected: "bg-red-50 text-danger",
  connecting: "bg-mist text-ink-soft",
};

export function StatusPill({ state }: { state: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
        STYLES[state] ?? "bg-mist text-ink-soft"
      }`}
    >
      {state.replace(/_/g, " ")}
    </span>
  );
}
