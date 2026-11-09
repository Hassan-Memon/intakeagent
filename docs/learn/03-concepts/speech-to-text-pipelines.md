# Speech-to-text pipelines

## Batch versus streaming

Speech-to-text comes in two shapes. **Batch** models (Whisper and its derivatives) take a
complete audio file and return text with word or segment timestamps. They are accurate and
simple to run. **Streaming** models (Deepgram, AssemblyAI real-time, NVIDIA Riva, Whisper with
VAD chunking) take a continuous audio stream and emit partial transcripts that are revised as
more audio arrives. They feel instant but are harder to host and to reason about.

IntakeAgent uses batch STT on short segments. Five seconds of audio becomes a complete file,
transcribed as a unit. You get near-real-time behaviour with batch simplicity. The cost is a
latency floor of one segment plus inference time.

## The provider interface

`backend/intakeagent/stt/base.py` defines a tiny `Protocol`:

    async def transcribe(audio: bytes, mime_type: str, *, session_id, vertical) -> list[TranscriptSegment]

Everything else in the system only sees `TranscriptSegment` objects (`id`, `text`,
`start_ms`, `end_ms`). The factory `get_stt_provider(settings)` chooses an implementation from
`STT_PROVIDER` or, with `auto`, picks faster-whisper if installed, then Groq if a key exists,
then the stub.

## The three implementations

**Stub (`stt/stub.py`).** Ignores the audio and returns the next line of a scripted intake.
This is what makes `DEMO_MODE` work without a model, and what the tests use. The scripts
cover every required field so a demo ends with a complete record.

**Groq Whisper (`stt/groq.py`).** Posts the file as multipart form data to Groq's
OpenAI-compatible `/audio/transcriptions` with `model=whisper-large-v3` and
`response_format=verbose_json` to get segment timestamps. It is free and fast, and the audio
leaves your machine, which the compliance doc flags.

**faster-whisper (`stt/faster_whisper.py`).** Runs Whisper locally through CTranslate2. The
`base` model with `int8` compute is roughly real time on a laptop CPU; `small` or `medium` on a
GPU is much better. Audio is written to a temp file (the library wants a path), transcribed with
`vad_filter=True` to skip silence, and the file is deleted. Inference is CPU bound, so it runs
in `asyncio.to_thread` to keep the event loop responsive.

## Timestamps and the session timeline

Each provider returns offsets relative to its own file. The service layer
(`IntakeService.add_segments`) adds the session's last known `end_ms` so the transcript stays
monotonic. The review UI uses `start_ms` to show a time column; a future playback feature
would use it to seek.

## Containers and codecs

Browsers record WebM/Opus (Chrome, Firefox) or MP4/AAC (Safari). Whisper decodes both through
ffmpeg or PyAV, and Groq accepts both. The `mime_type` travels with the frame so the provider
can pick a file extension; the content itself is opaque to the server.

## Accuracy levers

- **Prompting.** Whisper accepts an initial prompt; passing the vertical's vocabulary
  (drug names, legal terms) improves recognition. Not wired yet; see lesson 05.
- **Segment boundaries.** Cutting on silence instead of a fixed timer avoids split words.
- **Language.** Setting the language explicitly avoids misdetection on short clips.
- **Model size.** `large-v3` is noticeably better than `base` for accented speech and medical
  terms; cost is compute.

## Privacy and placement

The STT box is where audio is most exposed. Running faster-whisper next to the backend keeps
audio in process memory and never on disk (the temp file is deleted immediately; use a tmpfs
in production). Hosted STT requires a vendor agreement before real PHI is sent.
