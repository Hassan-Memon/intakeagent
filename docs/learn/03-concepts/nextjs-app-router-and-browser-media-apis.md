# Next.js App Router and browser media APIs

## App Router in one paragraph

Next.js 15's App Router maps folders under `app/` to URLs. `app/page.tsx` is `/`,
`app/intake/[id]/page.tsx` is `/intake/:id`, `app/layout.tsx` wraps every page (our header,
footer and skip link). Files are React components. By default they are **server components**:
they render on the server, can be `async`, can read databases or secrets, and ship no
JavaScript for themselves to the browser. Add `"use client"` at the top of a file and it becomes
a **client component**: it runs in the browser and can use state, effects, event handlers and
browser APIs.

## Where the line is drawn here

Pages are server components that do almost nothing: `app/intake/[id]/page.tsx` awaits
`params` (a Promise in Next 15) and renders `<IntakeClient sessionId={id} />`. Everything that
touches `WebSocket`, `MediaRecorder` or `useState` lives in `components/*Client.tsx` with
`"use client"`. This split is the idiom: keep the server boundary thin, push interactivity to
leaf components. If you ever see "window is not defined" during build, a browser API leaked
into a server component.

## Environment variables

Only variables prefixed `NEXT_PUBLIC_` are embedded into the client bundle, at **build time**.
`frontend/lib/api.ts` reads `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`; the Dockerfile
passes them as build args and Vercel sets them in project settings. Changing them requires a
rebuild, which surprises people coming from Python's runtime `os.environ`.

## Data fetching pattern

The client components fetch with `fetch()` inside `useEffect` and keep results in `useState`.
For an internal tool this is fine. Larger apps use a data library or server actions; the
principle is the same: the component declares what it needs and re-renders when it arrives.

## getUserMedia and MediaRecorder

`navigator.mediaDevices.getUserMedia({ audio: true })` prompts for microphone permission and
returns a `MediaStream`. It only works on `https://` or `localhost`, which matters for
deployment. `new MediaRecorder(stream, { mimeType })` encodes the stream; `start()`,
`stop()`, and the `dataavailable` event deliver `Blob`s. `MediaRecorder.isTypeSupported()`
picks a container the browser can produce (`frontend/lib/recorder.ts` prefers
`audio/webm;codecs=opus`, falls back to Ogg or MP4 for Safari).

The one gotcha covered in ADR-0005: a single recorder with `timeslice` yields fragments, so we
restart it per segment to get complete files.

## Web Audio for the level meter

`new AudioContext()`, `createMediaStreamSource(stream)`, `createAnalyserNode()`. Each
animation frame we call `getByteTimeDomainData`, compute RMS, and pass a 0 to 1 level to
`LevelMeter.tsx`. Use `requestAnimationFrame`, not `setInterval`, so the meter pauses when the
tab is hidden. Close the `AudioContext` when stopping to release the device.

## Accessibility that matters at a front desk

- The agent's question sits in a container with `aria-live="polite"` so screen readers
  announce it when it changes (`QuestionPanel.tsx`).
- The mic button uses `aria-pressed` to expose its state; the meter is `role="meter"`.
- Every input has a label; required fields are marked with both a visual asterisk and an
  sr-only "(required)".
- Focus rings are visible (`:focus-visible` in `globals.css`), colour is never the only signal,
  and `prefers-reduced-motion` disables the pulse animation.

## Tailwind 4 notes

Tailwind 4 is configured in CSS, not `tailwind.config.js`: `@import "tailwindcss"` plus an
`@theme` block declaring colour tokens (`--color-accent`), which become utilities
(`bg-accent`). `@apply` works on utilities only, not on your own classes, which is why the
button classes in `globals.css` spell out their utilities.

## Build and lint

`npm run build` type-checks (TypeScript `strict` with `noUncheckedIndexedAccess`), lints and
prerenders static routes. `/` and `/records` are static; `/intake/[id]` and `/review/[id]`
are dynamic. `output: "standalone"` in `next.config.ts` produces a self-contained server for
the Docker image.
