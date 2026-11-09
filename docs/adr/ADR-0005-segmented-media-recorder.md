# ADR-0005: Segmented MediaRecorder uploads instead of a continuous byte stream

- Status: accepted
- Date: 2026-11-09
- Deciders: Hassan Memon

## Context and problem statement

The browser's `MediaRecorder` API produces WebM/Opus (Chrome, Firefox) or MP4/AAC (Safari).
Called with a `timeslice`, it emits a `dataavailable` event every N milliseconds, but only the
first blob contains the container header; later blobs are fragments that only decode when
appended to everything before them. Whisper-class STT (faster-whisper, Groq) decodes a file,
not a fragment. How do we get transcribable audio to the server every few seconds?

## Considered options

1. Stream fragments with `timeslice`; on the server, append to a growing buffer and
   re-transcribe the whole file each time (or remux with ffmpeg).
2. Restart `MediaRecorder` every few seconds so each `stop` yields a complete, standalone file;
   send each file as one binary WebSocket frame.
3. Capture raw PCM with `AudioWorklet`, send 16 kHz frames, and run a streaming STT with VAD
   on the server.

## Decision outcome

Chosen option 2. `frontend/lib/recorder.ts` (`SegmentRecorder`) starts a recorder, stops it
after `segmentMs` (default 5000), emits the blob, and immediately starts a new recorder on the
same `MediaStream`. Each blob is a valid WebM file the backend can hand to any STT provider
unchanged. Segment offsets are shifted onto the session timeline in
`IntakeService.add_segments`.

### Consequences

- Good: zero server-side audio processing, no ffmpeg, no growing buffers; each segment is an
  independent unit of work, so one failed STT call loses five seconds, not the session.
- Good: hosted STT providers accept the frame as a file upload as-is.
- Good: the same mechanism works for Safari's MP4 output; only the MIME type changes.
- Bad: a word spoken across a segment boundary can be split or lost. In practice Whisper copes
  with clipped syllables reasonably, and intake speech has natural pauses. A later improvement
  is to end segments on silence (energy below a threshold for 400 ms) rather than on a timer.
- Bad: latency floor equals the segment length plus STT time. Five seconds is a conscious
  trade; two seconds is possible but increases per-call overhead.
- Bad: not suitable for real streaming partial transcripts; that is the WebRTC/AudioWorklet
  path described in ADR-0001.

## Confirmation

The WebSocket test in `tests/test_api.py::test_websocket_audio_and_finish` sends a binary
frame per segment and asserts the transcript, extraction and question come back. The stub STT
ignores content, so the protocol, not Whisper, is what is under test.
