# Learn IntakeAgent

Short lessons for a Python developer who knows FastAPI and LangGraph and is newer to browser
media APIs, WebSockets, Next.js, FHIR and OAuth2. Each lesson is 300 to 700 words and points at
real files in this repository.

1. [Architecture walkthrough](01-architecture-walkthrough.md): why each box exists, the request path end to end
2. [System design trade-offs](02-system-design-tradeoffs.md): scaling, failure modes, back-pressure, idempotency, what breaks first at 10x
3. Concepts (one file each):
   - [WebSockets and binary audio streaming](03-concepts/websockets-and-binary-audio-streaming.md)
   - [Speech-to-text pipelines](03-concepts/speech-to-text-pipelines.md)
   - [LangGraph structured extraction and interrupts](03-concepts/langgraph-structured-extraction-and-interrupts.md)
   - [FHIR R4 basics](03-concepts/fhir-r4-basics.md)
   - [OAuth2 for integrations (Clio)](03-concepts/oauth2-for-integrations-clio.md)
   - [PHI redaction and local-first LLM](03-concepts/phi-redaction-and-local-first-llm.md)
   - [Next.js App Router and browser media APIs](03-concepts/nextjs-app-router-and-browser-media-apis.md)
   - [SQLModel and pgvector](03-concepts/sqlmodel-and-pgvector.md)
4. [Interview talk track](04-interview-talk-track.md): 2 minute and 15 minute versions, numbers, likely questions
5. [Run it yourself](05-run-it-yourself.md): break it, extend it, observe it
