/**
 * Simulated intake WebSocket for the in-browser demo. Same interface as connectIntake() in
 * lib/ws.ts and the same message sequence as backend/intakeagent/api/ws.py, with short delays
 * so the status pill moves the way it does against the real backend.
 *
 * Audio frames are accepted and dropped: speech-to-text needs the real backend.
 */

import type { ClientMessage, ServerMessage } from "../types";
import type { IntakeSocket } from "../ws";
import { DemoError, demoService } from "./backend";

export function connectDemoIntake(
  sessionId: string,
  handlers: {
    onMessage: (msg: ServerMessage) => void;
    onOpen?: () => void;
    onClose?: (code: number) => void;
    onError?: () => void;
  },
): IntakeSocket {
  let open = false;
  let closed = false;
  const timers = new Set<ReturnType<typeof setTimeout>>();
  let queue: Promise<void> = Promise.resolve();

  const emit = (msg: ServerMessage) => {
    if (!closed) handlers.onMessage(msg);
  };
  const wait = (ms: number) =>
    new Promise<void>((resolve) => {
      const t = setTimeout(() => {
        timers.delete(t);
        resolve();
      }, ms);
      timers.add(t);
    });
  const enqueue = (job: () => Promise<void>) => {
    queue = queue.then(() => (closed ? undefined : job())).catch(() => undefined);
  };
  const errorOf = (e: unknown) => (e instanceof DemoError || e instanceof Error ? e.message : "error");

  const connectTimer = setTimeout(() => {
    timers.delete(connectTimer);
    if (closed) return;
    if (!demoService.exists(sessionId)) {
      closed = true;
      handlers.onClose?.(4404);
      return;
    }
    open = true;
    handlers.onOpen?.();
    const s = demoService.session(sessionId);
    emit({
      type: "ready",
      session_id: s.id,
      vertical: s.vertical,
      status: s.status,
      stt: "demo",
      question: s.next_question,
      record: s.record,
      missing_fields: s.missing_fields,
    });
  }, 200);
  timers.add(connectTimer);

  const handleText = (text: string) => {
    // Emitted synchronously so the UI leaves "listening" in the same tick as the send.
    emit({ type: "status", state: "thinking" });
    enqueue(async () => {
      await wait(450 + Math.random() * 400);
      try {
        const result = demoService.addText(sessionId, text);
        for (const segment of result.newSegments) emit({ type: "transcript", segment });
        emit({ type: "extraction", record: result.record, missing_fields: result.missing });
        if (result.question) emit({ type: "question", text: result.question, field: result.field });
      } catch (e) {
        emit({ type: "error", code: "invalid_state", message: errorOf(e) });
      }
      emit({ type: "status", state: "listening" });
    });
  };

  const handleFinish = () => {
    emit({ type: "status", state: "finishing" });
    enqueue(async () => {
      await wait(500);
      try {
        const s = demoService.finish(sessionId);
        emit({
          type: "awaiting_approval",
          session_id: s.id,
          record: s.record,
          missing_fields: s.missing_fields,
          review_url: `/review/${s.id}`,
        });
        emit({ type: "status", state: "awaiting_approval" });
      } catch (e) {
        emit({ type: "error", code: "invalid_state", message: errorOf(e) });
      }
    });
  };

  const send = (msg: ClientMessage) => {
    if (!open || closed) return;
    switch (msg.type) {
      case "text": {
        const text = msg.text.trim();
        if (text) handleText(text);
        break;
      }
      case "finish":
        handleFinish();
        break;
      case "ping":
        emit({ type: "pong" });
        break;
      default:
        break; // audio_meta: nothing to do without speech-to-text
    }
  };

  return {
    send,
    sendAudio: async () => {
      // Dropped on purpose: transcription runs on the real backend only.
    },
    close: () => {
      closed = true;
      open = false;
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
    },
  };
}
