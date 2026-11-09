import { RecordsClient } from "@/components/RecordsClient";

export default function RecordsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Approved records</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Every row here was approved by a person. Export status shows where it went.
        </p>
      </div>
      <RecordsClient />
    </div>
  );
}
