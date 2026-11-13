# IntakeAgent backend

FastAPI + LangGraph service. See the repository README for the big picture and
`docs/protocol.md` for the WebSocket protocol.

```bash
uv sync
DEMO_MODE=1 uv run uvicorn intakeagent.main:app --reload
uv run pytest

# Reference data
uv run python -m intakeagent.verify.sanctions refresh --out data/sanctions.json  # OFAC + UN
uv run python -m intakeagent.verify.sanctions screen "Some Company Ltd" --list data/sanctions.json
uv run python -m intakeagent.verify.terminology snapshot  # regenerate the NLM snapshot (+ demo copy)
```

Package layout:

| Path | Purpose |
| --- | --- |
| `intakeagent/config.py` | Settings from environment (pydantic-settings) |
| `intakeagent/schemas/` | PatientIntake and LegalIntake with required-field metadata and evidence spans |
| `intakeagent/redaction/` | Regex PHI redaction with local re-hydration |
| `intakeagent/stt/` | Speech-to-text providers: stub, Groq Whisper, faster-whisper |
| `intakeagent/llm/` | Provider abstraction (OpenInfer, Ollama, Groq, Gemini, OpenRouter, stub) |
| `intakeagent/graph/` | LangGraph intake graph with HITL interrupt |
| `intakeagent/verify/` | Reference checks before review: RxNorm, RxClass and ICD-10-CM (NLM, with bundled snapshot) and local OFAC and UN sanctions screening |
| `intakeagent/exporters/` | FHIR R4 Bundle (with reviewer-accepted codes) and Clio API v4 exporters |
| `intakeagent/db/` | SQLModel persistence and pgvector protocol RAG |
| `intakeagent/api/` | REST routes, WebSocket endpoint, session service |
