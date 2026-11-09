# WebSockets and binary audio streaming

## The problem HTTP does not solve

HTTP is request and response: the client asks, the server answers, the connection is done.
An intake session is a conversation. Audio flows up continuously and transcript, extraction
and questions flow down whenever the server has them. Polling would work but wastes requests
and adds latency; Server-Sent Events only flow down. A WebSocket is a single TCP connection,
upgraded from HTTP, over which either side can send a message at any time.

## What a WebSocket message is

Each message is a frame with a type: **text** (UTF-8, we use JSON) or **binary** (raw bytes).
Frames are delivered in order and whole; you never get half a message. That ordering is the
property we exploit: `frontend/lib/ws.ts` sends a small JSON frame
`{"type": "audio_meta", "mime": "audio/webm;codecs=opus", "seq": 3}` and then the binary audio
frame, and the server knows they belong together because nothing can arrive between them on
that connection.

## The server side in FastAPI

`backend/intakeagent/api/ws.py` declares the endpoint with `@router.websocket("/ws/intake/{session_id}")`.
The handler calls `await ws.accept()`, then loops on `await ws.receive()`, which returns a dict
with either a `"text"` or a `"bytes"` key, or a disconnect event. Text frames are parsed as
JSON and dispatched on `type`; bytes go to the STT provider. Because STT and the graph are
blocking, the handler runs them with `await asyncio.to_thread(...)` so other connections keep
being served by the event loop.

Closing with a custom code is how we signal application errors before accepting: an unknown
session gets `await ws.close(code=4404)`. Codes 4000 to 4999 are reserved for applications.

## The client side in the browser

`new WebSocket(url)` opens the connection. `ws.binaryType = "arraybuffer"` tells the browser
how to hand us binary frames (we never receive any, but it is good hygiene). `ws.send(string)`
sends a text frame; `ws.send(arrayBuffer)` sends binary. `onmessage` receives both; we check
`typeof ev.data === "string"` and parse JSON.

## Why audio is sent as files, not a stream

A natural instinct is to stream audio bytes as they are produced. `MediaRecorder` with a
`timeslice` seems to offer exactly that, but only the first blob has the container header;
later blobs are fragments that cannot be decoded on their own. Whisper-style models want a
file. So `frontend/lib/recorder.ts` restarts the recorder every five seconds, producing a
complete WebM each time, and sends each one as one binary frame. The trade-off and the
alternatives are in `docs/adr/ADR-0005-segmented-media-recorder.md`.

## Connection lifecycle and failure

WebSockets die silently on bad networks. Two defences: a `ping`/`pong` pair in the protocol so
the client can detect a dead connection, and server-side state that lives in the database so a
reconnect can continue the same session. The client currently shows a `disconnected` pill; a
reconnect-with-backoff loop is a good exercise (see lesson 05).

## CORS does not apply, Origin does

Browsers do not run CORS preflight for WebSocket upgrades. They do send an `Origin` header,
which the server can check. We rely on `CORS_ORIGINS` for REST and leave WebSocket origin
checks to the auth layer; `docs/compliance.md` lists it as a gap.

## Where to read more

- `docs/protocol.md`: the full message catalogue.
- `backend/tests/test_api.py::test_websocket_audio_and_finish`: a complete session driven
  through Starlette's test client.
