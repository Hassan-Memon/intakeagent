import { IntakeClient } from "@/components/IntakeClient";

// Next.js 15: dynamic route params arrive as a Promise in server components.
export default async function IntakePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <IntakeClient sessionId={id} />;
}
