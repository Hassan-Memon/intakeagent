# IntakeAgent backend

FastAPI + LangGraph service. See the repository README for the big picture and
`docs/protocol.md` for the WebSocket protocol.

```bash
uv sync
DEMO_MODE=1 uv run uvicorn intakeagent.main:app --reload
uv run pytest
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
| `intakeagent/exporters/` | FHIR R4 Bundle and Clio API v4 exporters |
| `intakeagent/db/` | SQLModel persistence and pgvector protocol RAG |
| `intakeagent/api/` | REST routes, WebSocket endpoint, session service |
