import { WS_URL } from "./api";
import type { ClientMessage, ServerMessage } from "./types";

export interface IntakeSocket {
  send: (msg: ClientMessage) => void;
  sendAudio: (blob: Blob, mime: string, seq: number) => Promise<void>;
  close: () => void;
}

/**
 * Open the intake WebSocket for a session.
 *
 * JSON control frames and binary audio frames share one socket. Before each audio frame we
 * send an `audio_meta` frame so the server knows the container type; WebSocket frames are
 * ordered, so the pair always arrives together.
 */
export function connectIntake(
  sessionId: string,
  handlers: {
    onMessage: (msg: ServerMessage) => void;
    onOpen?: () => void;
    onClose?: (code: number) => void;
    onError?: () => void;
  },
): IntakeSocket {
  const ws = new WebSocket(`${WS_URL}/ws/intake/${sessionId}`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => handlers.onOpen?.();
  ws.onclose = (ev) => handlers.onClose?.(ev.code);
  ws.onerror = () => handlers.onError?.();
  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") return;
    try {
      handlers.onMessage(JSON.parse(ev.data) as ServerMessage);
    } catch {
      // ignore malformed frames
    }
  };

  const send = (msg: ClientMessage) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };

  return {
    send,
    sendAudio: async (blob, mime, seq) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      send({ type: "audio_meta", mime, seq });
      ws.send(await blob.arrayBuffer());
    },
    close: () => ws.close(1000, "client done"),
  };
}
