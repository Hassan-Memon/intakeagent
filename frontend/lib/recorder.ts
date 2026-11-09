/**
 * SegmentRecorder: microphone capture that emits complete audio files every few seconds.
 *
 * Why not one long MediaRecorder with a timeslice? Because only the first `dataavailable`
 * blob contains the WebM header; later blobs are headerless fragments that Whisper cannot
 * decode on their own. Restarting the recorder per segment gives us standalone files that
 * any STT provider can transcribe independently (see docs/adr/ADR-0005).
 *
 * It also wires an AnalyserNode so the UI can show a live input level.
 */
export class SegmentRecorder {
  private recorder: MediaRecorder | null = null;
  private chunks: BlobPart[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private raf = 0;
  private seq = 0;

  readonly mimeType: string;

  constructor(
    private readonly stream: MediaStream,
    private readonly onSegment: (blob: Blob, mime: string, seq: number) => void,
    private readonly onLevel: (level: number) => void,
    private readonly segmentMs = 5000,
  ) {
    this.mimeType = SegmentRecorder.pickMimeType();
  }

  static pickMimeType(): string {
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    if (typeof MediaRecorder === "undefined") return "audio/webm";
    return candidates.find((c) => MediaRecorder.isTypeSupported(c)) ?? "audio/webm";
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.startLevelMeter();
    this.startSegment();
  }

  stop(): void {
    this.running = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    cancelAnimationFrame(this.raf);
    this.audioCtx?.close().catch(() => undefined);
    this.audioCtx = null;
    this.stream.getTracks().forEach((t) => t.stop());
    this.onLevel(0);
  }

  private startSegment(): void {
    this.chunks = [];
    const recorder = new MediaRecorder(this.stream, { mimeType: this.mimeType });
    this.recorder = recorder;
    recorder.ondataavailable = (ev) => {
      if (ev.data.size > 0) this.chunks.push(ev.data);
    };
    recorder.onstop = () => {
      const blob = new Blob(this.chunks, { type: this.mimeType });
      // Skip near-empty segments (header only) to avoid pointless STT calls.
      if (blob.size > 1024) this.onSegment(blob, this.mimeType, this.seq++);
      if (this.running) this.startSegment();
    };
    recorder.start();
    this.timer = setTimeout(() => {
      if (recorder.state !== "inactive") recorder.stop();
    }, this.segmentMs);
  }

  private startLevelMeter(): void {
    const Ctx = window.AudioContext;
    if (!Ctx) return;
    this.audioCtx = new Ctx();
    const source = this.audioCtx.createMediaStreamSource(this.stream);
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 512;
    source.connect(this.analyser);
    const data = new Uint8Array(this.analyser.fftSize);
    const tick = () => {
      if (!this.analyser) return;
      this.analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const v of data) {
        const x = (v - 128) / 128;
        sum += x * x;
      }
      const rms = Math.sqrt(sum / data.length);
      this.onLevel(Math.min(1, rms * 3));
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }
}
