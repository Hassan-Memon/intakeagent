import { DEMO_MODE } from "@/lib/api";

export const REPO_URL = "https://github.com/Hassan-Memon/intakeagent";

/** Shown on every page when NEXT_PUBLIC_DEMO_MODE=1. Renders nothing otherwise. */
export function DemoBanner() {
  if (!DEMO_MODE) return null;
  return (
    <div role="note" aria-label="Demo notice" className="border-b border-warn/30 bg-warn-soft">
      <p className="mx-auto max-w-6xl px-4 py-2.5 text-sm text-ink">
        <span className="font-semibold">Live demo:</span> the backend is simulated in your
        browser and nothing you type leaves this page.{" "}
        <a
          href={REPO_URL}
          className="font-semibold text-accent-strong underline"
          target="_blank"
          rel="noopener noreferrer"
        >
          Run the real stack with docker compose
        </a>
        . Sample people are fictional; this is not a clinical or legal system.
      </p>
    </div>
  );
}
