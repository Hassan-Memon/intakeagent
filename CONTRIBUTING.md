# Contributing to IntakeAgent

Thanks for your interest. This project is a reference MVP, so contributions that keep it
small, readable and well documented are the most welcome.

## Ground rules

- Keep `DEMO_MODE=1` working with zero API keys. Every new integration needs a stub.
- No PHI or real client data in tests, fixtures, screenshots or issues. Use obviously fake names.
- Any step that sends text to a non-local LLM must go through `intakeagent.redaction`.
- Human approval stays mandatory before export. Do not add an "auto-export" path.
- Do not use em-dashes in docs or comments.

## Development setup

```bash
# backend
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
uv run uvicorn intakeagent.main:app --reload

# frontend
cd frontend
npm ci
npm run dev
```

## Commits and pull requests

- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`.
- One logical change per commit. Keep PRs under roughly 400 lines where you can.
- CI must be green: ruff, pytest, eslint, `next build`, `docker compose config`.
- If you add an architectural decision, add an ADR in `docs/adr/` using the MADR template.
- If you introduce a concept that is new to a Python-only developer, add a short lesson under
  `docs/learn/03-concepts/`.

## Reporting bugs

Open an issue with steps to reproduce, expected behaviour and actual behaviour. For anything
security related, follow `SECURITY.md` instead of opening a public issue.
