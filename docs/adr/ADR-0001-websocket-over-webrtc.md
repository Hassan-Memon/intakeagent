# ADR-0001: WebSocket transport for the MVP, WebRTC later

- Status: accepted
- Date: 2026-11-09
- Deciders: Hassan Memon

## Context and problem statement

The browser must send microphone audio to the backend and receive transcript segments,
structured extraction updates and the agent's questions in near real time. The two realistic
options are a WebSocket carrying audio frames, or WebRTC (a media track to a server-side peer,
plus a data channel or separate signalling for JSON).

## Decision drivers

- Ship a working, debuggable MVP on free hosting (Render, Vercel) with no media server.
- Batch STT models (Whisper) need complete audio files, not RTP packets.
- A single developer new to browser media APIs needs to be able to reason about the pipeline.
- Latency target for intake is "a few seconds per utterance", not conversational sub-second.

## Considered options

1. WebSocket: JSON control frames plus binary audio frames on one connection.
2. WebRTC: audio track to a media server (LiveKit, mediasoup, Janus) that forwards to STT;
   data channel for JSON.
3. HTTP POST per segment plus Server-Sent Events for responses.

## Decision outcome

Chosen option 1, WebSocket, because it needs no extra infrastructure, works through every
free host that supports HTTP upgrade, carries both audio and JSON on one ordered connection,
and matches how batch STT wants its input. Implementation: `backend/intakeagent/api/ws.py`
and `frontend/lib/ws.ts`; protocol in `docs/protocol.md`.

### Consequences

- Good: one connection per session, trivial local debugging with `websocat`, works on Render
  free tier, no TURN/STUN, no media server bill.
- Good: ordered frames let a JSON `audio_meta` precede each binary frame without correlation ids.
- Bad: TCP head-of-line blocking; a slow network delays audio rather than dropping it. For
  intake that is acceptable.
- Bad: no built-in echo cancellation, jitter buffer or adaptive bitrate; we rely on the
  browser's `getUserMedia` processing.
- Bad: not suitable for a two-way voice conversation with a speaking agent; the agent currently
  "speaks" as text.

## The WebRTC path (when and how)

Move to WebRTC when any of these become requirements: spoken agent replies with barge-in,
telephony (SIP) ingress, or sub-second streaming STT. Plan: run a LiveKit server (self-hosted
or their free tier), publish the mic track from the browser, have a Python agent participant
consume the track and feed a streaming STT (Deepgram-style or faster-whisper with VAD
chunking), and keep the existing LangGraph graph untouched because it already consumes
transcript segments, not audio. The REST surface and the review screen do not change.

## Pros and cons of the other options

- WebRTC: best latency and audio quality, but adds a media server, TURN, and a second
  protocol for JSON; too much for a zero-cost MVP.
- HTTP + SSE: simplest to proxy, but two connections, no binary SSE, and segment uploads as
  separate requests add overhead and ordering concerns.
