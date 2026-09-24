# ADR 0002: challenge session lifecycle

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

The host previously treated CAPTCHA as a boolean: `captcha_visible: true`. That model cannot express
what actually happens. A challenge appears, the human interacts, the grid changes into a new round,
it changes again, and then the widget disappears. It also cannot distinguish a challenge that stopped
the flow before any submission from a provider that *rejected* a submission it received — the same
widget on screen, with opposite meanings.

## Decision

Model a challenge as a session with a lifecycle:

```text
ChallengeSession
  -> 0..N ChallengeRoundObservation
  -> ChallengeObservation (a factual snapshot, decides nothing)
  -> ChallengeDecision (domain outcome)
```

Statuses form an explicit state machine (`DETECTED`, `ACTIVE`, `ROUND_CHANGED`, `WAITING_FOR_HUMAN`,
`DISAPPEARED`, `PROVIDER_REJECTED`, `COMPLETED`, `UNKNOWN`). Invalid transitions raise instead of
being silently ignored: a swallowed transition would hide exactly the bug the session exists to
prevent. `COMPLETED` is terminal, and observing a completed session is a caller error.

A round is a **structural** change. "Disappeared" is a lifecycle transition, not a round, so it does
not increment the round counter.

Presence is never success. A vanished challenge yields `DISAPPEARED`, and the policy reports
`RESOLVED_EXTERNALLY` — never a success the guard cannot prove.

## Consequences

- The host can observe a human solving a challenge without the guard interacting: rounds are recorded
  while the human works, and the disappearance ends the session.
- `PROVIDER_REJECTED` is terminal for observation. A later round is still recorded for the audit but
  does not reopen tracking, because continuing in the automated browser after a rejection is
  pointless — that is the human final mile.
- The round history is durable evidence of what happened, which the boolean never was.
