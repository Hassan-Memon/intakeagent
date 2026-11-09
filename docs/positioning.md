# Positioning

## Who it is for

- **Independent and small-group clinics** (1 to 20 providers) where the front desk still
  hands patients a clipboard and re-types it into the EHR. They own the intake workflow, they
  feel the staffing pressure, and they can adopt a tool without a hospital procurement cycle.
- **Small law firms and solo practitioners** who lose billable time to first-call intake and
  need a conflict check before a matter is opened. Many already use Clio.
- **Regional buyers (UK, UAE, KSA)** for whom "where does the audio go" is the first question.
  Local-first inference answers it.
- **Technical evaluators** (CTOs, agency partners) who want a reference implementation of a
  voice agent with structured output, human approval and standards-based export they can fork.

## The problem

Intake is a conversation that gets flattened into a form. Patients and clients repeat
themselves, staff transcribe under time pressure, required fields go missing, and the output
is a PDF or a free-text note that no downstream system can use. The cost is measured in staff
hours, clinician minutes at the start of each visit, and matters opened without a clean
conflict check.

## Alternatives and why IntakeAgent wins

| Alternative | What it does well | Where it falls short | IntakeAgent's answer |
| --- | --- | --- | --- |
| **Manual intake** (clipboard, phone call, receptionist) | Zero software, human judgement | Slow, error prone, nothing structured, no evidence trail | Same conversation, but captured once, structured, and every value linked to the words that produced it |
| **Generic chatbots** (web chat widgets, LLM wrappers) | Cheap, quick to deploy | Text only, no schema, hallucination risk, no idea what is still missing, no export | Voice first, typed schema per vertical, missing-field detector drives the questions, FHIR and Clio out |
| **EHR built-in forms / patient portals** | Already integrated, billing codes | Form fatigue, low completion, fixed fields, nothing conversational, heavy vendor lock-in | Sits in front of the EHR and writes a standard FHIR Bundle any R4 server accepts; the clinic keeps its EHR |
| **Clio Grow** (and similar legal CRMs) | Great pipeline and e-signature, native to Clio | Intake is still web forms the client fills in; no voice, no follow-up questions, no extraction from a narrative | Talks to the client, extracts matter type, parties, dates and conflict names, then creates the Clio Contact and Matter via the same API Grow uses |
| **Ambient clinical scribes** (visit documentation tools) | Excellent at SOAP notes during the encounter | Priced for the clinician, not the front desk; built around the visit, not pre-visit intake; cloud-only PHI handling | Purpose-built for pre-visit intake, runs on your own inference box, open source |
| **Call-centre AI / IVR voice bots** | Scale, telephony | Rigid scripts, poor with narrative answers, no structured clinical/legal output | Conversational, schema-driven, exports standards |

## Why this design wins

1. **Human approval is the product, not a feature.** Clinics and firms are liable for the
   record. A graph that cannot export without a person pressing Approve is easier to buy than
   one that promises accuracy.
2. **Evidence spans turn review from re-reading into spot-checking.** Hover a field, see the
   sentence it came from. Review time drops and trust goes up.
3. **Local-first is a regional unlock.** UAE and KSA health data residency rules and UK NHS
   expectations are hard for cloud-only tools. Pointing the LLM at Ollama or an OpenInfer box
   is a configuration change here.
4. **Standards out.** FHIR R4 and Clio v4 mean integration is "point it at your server", not a
   custom connector per customer.
5. **Runs free, scales honestly.** Vercel, Render, Neon and Groq free tiers host a working
   pilot. The system design doc says what breaks first at 10x and how to fix it.

## What it is not

- Not a medical device and not clinical decision support. It records what the patient said.
- Not legal advice. It records what the client said and prepares a matter for a lawyer.
- Not a replacement for an EHR or practice management system. It feeds them.

## One-line pitch by audience

- **Clinic manager:** "Your patients talk; your EHR gets a clean FHIR record your staff approved."
- **Managing partner:** "First call to conflict-checked Clio matter, with the client's own words
  attached to every field."
- **CTO:** "LangGraph, FastAPI, Next.js, pgvector, FHIR, OAuth2, HITL interrupts, zero-key demo,
  all Apache-2.0."
