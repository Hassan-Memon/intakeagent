import type { Metadata } from "next";
import Link from "next/link";
import { DemoBanner } from "@/components/DemoBanner";
import "./globals.css";

export const metadata: Metadata = {
  title: "IntakeAgent",
  description: "Voice-first intake for clinics and law firms with human approval on every record.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <DemoBanner />
        <header className="border-b border-line bg-white">
          <nav
            className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3"
            aria-label="Primary"
          >
            <Link href="/" className="flex items-center gap-2 text-lg font-bold text-ink">
              <span
                aria-hidden="true"
                className="inline-block h-3 w-3 rounded-full bg-accent"
              />
              IntakeAgent
            </Link>
            <div className="flex items-center gap-1 text-sm">
              <Link href="/" className="rounded-lg px-3 py-2 hover:bg-mist">
                New intake
              </Link>
              <Link href="/records" className="rounded-lg px-3 py-2 hover:bg-mist">
                Records
              </Link>
            </div>
          </nav>
        </header>
        <main id="main" className="mx-auto max-w-6xl px-4 py-8">
          {children}
        </main>
        <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-ink-soft">
          Every record is reviewed by a person before it is exported. Demo data only.
        </footer>
      </body>
    </html>
  );
}
