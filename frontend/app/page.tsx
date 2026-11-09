import { StartIntake } from "@/components/StartIntake";

export default function HomePage() {
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight">Start a new intake</h1>
        <p className="max-w-2xl text-ink-soft">
          Choose the kind of intake. The assistant listens, asks the follow-up questions a good
          coordinator would, and prepares a structured record for you to review and approve.
        </p>
      </section>
      <StartIntake />
    </div>
  );
}
