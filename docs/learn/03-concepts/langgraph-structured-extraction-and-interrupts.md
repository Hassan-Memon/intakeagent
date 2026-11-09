# LangGraph: structured extraction and interrupts

## Why a graph for a conversation

A chat loop can be a `while` loop. The reasons to use LangGraph here are state with
reducers, conditional routing, a checkpointer keyed by thread, and `interrupt()`. Together
they let the same compiled graph be invoked once per utterance, remember everything, decide
whether to ask or stop, and pause for a human without holding a thread open.

## State and reducers

`backend/intakeagent/graph/state.py` defines `IntakeState` as a `TypedDict`. Two keys are
annotated with `operator.add`:

    transcript_segments: Annotated[list[dict], operator.add]
    questions_asked: Annotated[list[str], operator.add]

A reducer tells LangGraph how to merge a node's (or an input's) value into the existing state.
With `operator.add`, each invocation appends new segments rather than replacing the list. Keys
without a reducer are overwritten. This is how a per-utterance invocation accumulates a whole
conversation.

## Nodes and edges

`graph/builder.py` adds six nodes and wires them:

    START -> merge_transcript -> extract -> detect_missing
    detect_missing --(finished? no)--> ask_next_question -> END
    detect_missing --(finished? yes)--> await_approval -> export -> END

`add_conditional_edges("detect_missing", route_after_missing, {...})` picks the branch from a
function of state. Each node is a plain function `(state) -> dict` returning only the keys it
changes.

## Structured extraction

The `extract` node delegates to an `Extractor`. The LLM implementation uses
`model.with_structured_output(PatientIntake)`: LangChain converts the Pydantic class to a JSON
Schema, asks the model to answer in that shape (via tool calling or JSON mode depending on the
provider), and parses the reply back into a `PatientIntake`. Because every field is an
`Extracted[T]` with a `quote`, the model is asked to cite the phrase each value came from;
`attach_evidence` then finds that phrase in the transcript to get character offsets.

Two robustness tricks: `merge_records` keeps earlier values when a re-extraction leaves a
field empty, and any exception falls back to the rule-based extractor so a flaky model never
stalls a session.

## Checkpointer and threads

`g.compile(checkpointer=MemorySaver())` turns on persistence. Every `invoke` passes
`config={"configurable": {"thread_id": session_id}}`. LangGraph loads that thread's last
checkpoint, applies the new input through the reducers, runs the graph, and saves. From the
caller's view, the graph "remembers" the session. Swap `MemorySaver` for
`langgraph-checkpoint-postgres` and the memory survives restarts.

## interrupt() and Command(resume=...)

`await_approval` calls `interrupt(payload)`. On the first pass this raises internally,
LangGraph saves the checkpoint with the node marked pending, and `invoke` returns a result
containing `__interrupt__` with the payload. The graph is now parked. Later, the service calls

    graph.invoke(Command(resume={"approved": True, "record": edits}), config)

LangGraph re-runs `await_approval` from the top; this time `interrupt()` returns the resume
value instead of pausing. The node validates the edits and returns `approved=True`; execution
continues to `export`. Two things to remember: code before `interrupt()` in the node runs twice,
so keep it side-effect free; and `graph.get_state(config).next` tells you whether a thread is
parked (`IntakeService.approve` uses that to decide whether to rebuild the interrupt first).

## Seeing it in tests

`backend/tests/test_graph.py` is the best reading order: a turn that asks for the phone
number, a repeated question softened with "Sorry, I did not catch that", an interrupt whose
payload is inspected, a resume with edits that triggers export, and a rejection that does not.
