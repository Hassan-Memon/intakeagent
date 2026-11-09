"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { SegmentRecorder } from "@/lib/recorder";
import { connectIntake, type IntakeSocket } from "@/lib/ws";
import type { FieldSpec, IntakeRecord, ServerMessage, TranscriptSegment, Vertical } from "@/lib/types";
import { vertLabel } from "@/lib/format";
import { LevelMeter } from "./LevelMeter";
import { QuestionPanel } from "./QuestionPanel";
import { StatusPill } from "./StatusPill";
import { TranscriptPanel } from "./TranscriptPanel";

type ConnState = "connecting" | "listening" | "transcribing" | "thinking" | "finishing" | "awaiting_approval" | "disconnected";

export function IntakeClient({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const socketRef = useRef<IntakeSocket | null>(null);
  const recorderRef = useRef<SegmentRecorder | null>(null);

  const [vertical, setVertical] = useState<Vertical | null>(null);
  const [specs, setSpecs] = useState<FieldSpec[]>([]);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [record, setRecord] = useState<IntakeRecord>({});
  const [missing, setMissing] = useState<string[]>([]);
  const [question, setQuestion] = useState<string | null>(null);
  const [field, setField] = useState<string | null>(null);
  const [conn, setConn] = useState<ConnState>("connecting");
  const [recording, setRecording] = useState(false);
  const [level, setLevel] = useState(0);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sttName, setSttName] = useState<string>("");

  const busy = conn === "transcribing" || conn === "thinking" || conn === "finishing";

  const onMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "ready":
          setVertical(msg.vertical);
          setQuestion(msg.question);
          setRecord(msg.record);
          setMissing(msg.missing_fields);
          setSttName(msg.stt);
          setConn(msg.status === "recording" ? "listening" : "awaiting_approval");
          break;
        case "status":
          setConn(msg.state as ConnState);
          break;
        case "transcript":
          setSegments((prev) => [...prev, msg.segment]);
          break;
        case "extraction":
          setRecord(msg.record);
          setMissing(msg.missing_fields);
          break;
        case "question":
          setQuestion(msg.text);
          setField(msg.field);
          break;
        case "awaiting_approval":
          setConn("awaiting_approval");
          stopRecording();
          router.push(`/review/${msg.session_id}`);
          break;
        case "error":
          setError(msg.message);
          break;
        default:
          break;
      }
    },
    [router],
  );

  // Load the session (field specs, any earlier transcript) then open the socket.
  useEffect(() => {
    let cancelled = false;
    api
      .getSession(sessionId)
      .then((s) => {
        if (cancelled) return;
        setSpecs(s.field_specs);
        setSegments(s.transcript_segments);
        setVertical(s.vertical);
        if (s.status !== "recording") {
          router.replace(`/review/${sessionId}`);
          return;
        }
        socketRef.current = connectIntake(sessionId, {
          onMessage,
          onClose: () => setConn("disconnected"),
          onError: () => setError("Connection to the backend was lost."),
        });
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Session not found"));
    return () => {
      cancelled = true;
      socketRef.current?.close();
      recorderRef.current?.stop();
    };
  }, [sessionId, onMessage, router]);

  function stopRecording() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  }

  async function toggleRecording() {
    if (recording) {
      stopRecording();
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new SegmentRecorder(
        stream,
        (blob, mime, seq) => void socketRef.current?.sendAudio(blob, mime, seq),
        setLevel,
      );
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      setError("Microphone access was denied. You can type your answers instead.");
    }
  }

  function sendTyped(e: React.FormEvent) {
    e.preventDefault();
    const text = typed.trim();
    if (!text) return;
    socketRef.current?.send({ type: "text", text });
    setTyped("");
  }

  function finish() {
    stopRecording();
    socketRef.current?.send({ type: "finish" });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="label">{vertical ? vertLabel(vertical) : ""} intake</p>
          <h1 className="text-2xl font-bold tracking-tight">Live intake</h1>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill state={conn} />
          {sttName && <span className="text-xs text-ink-soft">speech: {sttName}</span>}
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <section className="card space-y-5 lg:col-span-3">
          <div className="flex flex-wrap items-center gap-4">
            <button
              type="button"
              onClick={toggleRecording}
              disabled={conn === "disconnected" || conn === "awaiting_approval"}
              aria-pressed={recording}
              className={`${recording ? "btn-danger" : "btn-primary"} min-w-44`}
            >
              <span
                aria-hidden="true"
                className={`inline-block h-2.5 w-2.5 rounded-full ${
                  recording ? "animate-pulse bg-danger" : "bg-white"
                }`}
              />
              {recording ? "Stop microphone" : "Start microphone"}
            </button>
            <LevelMeter level={level} active={recording} />
            <span className="text-xs text-ink-soft">
              {recording
                ? "Audio is sent in short segments as you speak."
                : sttName === "stub"
                  ? "Demo mode: each segment plays the next scripted line."
                  : "Press to start."}
            </span>
          </div>

          <div>
            <p className="label">Transcript</p>
            <div className="mt-2 max-h-96 overflow-y-auto pr-1">
              <TranscriptPanel segments={segments} />
            </div>
          </div>

          <form onSubmit={sendTyped} className="flex gap-2">
            <label htmlFor="typed" className="sr-only">
              Type an answer
            </label>
            <input
              id="typed"
              className="input"
              placeholder="Prefer to type? Enter an answer here."
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={conn === "disconnected" || conn === "awaiting_approval"}
            />
            <button type="submit" className="btn-secondary" disabled={!typed.trim() || busy}>
              Send
            </button>
          </form>
        </section>

        <aside className="card space-y-6 lg:col-span-2">
          <QuestionPanel question={question} field={field} specs={specs} missing={missing} busy={busy} />
          <div className="border-t border-line pt-4">
            <button
              type="button"
              onClick={finish}
              disabled={conn === "disconnected" || conn === "awaiting_approval" || segments.length === 0}
              className="btn-primary w-full"
            >
              Finish and review
            </button>
            <p className="mt-2 text-center text-xs text-ink-soft">
              {missing.length > 0
                ? `${missing.length} required detail${missing.length === 1 ? "" : "s"} still missing. You can fill them in on the review screen.`
                : "All required details captured."}
            </p>
            <p className="sr-only">{Object.keys(record).length} fields in record</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
