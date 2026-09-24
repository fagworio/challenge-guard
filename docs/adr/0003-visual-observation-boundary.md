# ADR 0003: visual observation boundary

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

A screenshot can answer "what kind of challenge is this?" more reliably than the DOM, especially for
providers that render inside a cross-origin iframe. It can also carry the whole application form,
the candidate's name and the resume being uploaded.

## Decision

Visual classification is **disabled by default** and, when enabled, is restricted to *structure*.

1. `vision.enabled = false` is the default. Nothing is captured, computed or transmitted unless the
   host opts in.
2. When enabled, the pipeline is: locate the challenge, crop to it, drop surrounding context, and
   classify only that region. A full-page screenshot is never sent to a remote model by default.
3. The classifier's output schema has no `answer`, `solution`, `tiles`, `coordinates`, `clicks` or
   `token` field. The schema itself is the boundary: a field that does not exist cannot be filled in
   by a future contributor in a hurry.
4. Persisted by default: SHA-256, dimensions, classification, provider, confidence. Not persisted by
   default: the image.
5. Classification output is still only an observation. It feeds `ChallengeObservation`; it never
   produces a decision on its own, and it can never resolve anything.

## Consequences

- The useful part of visual analysis — knowing what kind of challenge this is — is available without
  making the library a solver.
- A host that enables vision takes on an explicit, documented privacy decision instead of inheriting
  one silently.
- Until implementation lands (CG-016/CG-017), the guarantee is structural: the boundary is written
  down before the capability exists, so the first implementation has a shape to fit.
