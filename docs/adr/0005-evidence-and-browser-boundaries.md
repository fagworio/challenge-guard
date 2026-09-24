# ADR 0005: evidence redaction, network requirements and the browser adapter

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

CG-012 to CG-015 introduce the first capabilities that touch the outside world: a description of what
a challenge widget needs from the network, a persistable evidence model, and a real browser adapter.
Each is a place where a library can quietly become either a network authoriser, a payload store, or
a set of site-specific hacks.

## Decision

### Network requirements (CG-012)

The library **describes**; the host **authorises**. `ChallengeNetworkRequirement` names origins,
methods, path patterns and an expected request budget. It grants nothing, and there is no separate
budget to share: the host keeps its own counters, and challenge traffic can never consume upload or
submission credit.

Three rules are enforced by construction rather than by convention:

1. A catch-all path pattern (`^/.*$`) is refused outright. Its absence is the only way to say "path
   unknown", and the host must read that as unknown rather than as permission.
2. A wildcard origin requires a known path. A wildcard with an open path authorises an entire
   domain — a defect already observed in a production upload policy.
3. `GENERIC` declares no requirement at all. "I do not know" must never masquerade as "anything
   goes".

Every declared path is one actually observed, and each marker carries an `EvidenceLevel`
(`OBSERVED`, `FIXTURE`, `INFERRED`) with a short provenance reference. That level is maintenance
metadata: a test asserts it does **not** change any decision, so an inferred pattern cannot become a
strong classification by existing.

### Evidence redaction (CG-013)

`ChallengeEvidence` is the only persistable shape, and it is an **allowlist**. A denylist always
forgets a field; an allowlist fails closed. Nothing an observer holds internally reaches it.

A property test serialises the whole evidence object and searches for sentinel payloads — response
tokens, sitekeys, cookies, authorisation headers, form values, e-mail and phone. Zero occurrences.
Two independent guards produce that result: the structural fingerprint refuses content-like signals
before redaction, and the evidence allowlist drops everything undeclared.

### Browser adapter (CG-014)

The adapter is deliberately thin: it translates Playwright objects into library models and contains
no policy. It is not exported from the package root, so importing `challenge_guard` never requires
Playwright.

Listeners are managed explicitly by `attach`/`detach`. `attach` is idempotent. Navigation clears
transient observation, so a response from the previous page cannot classify the current session. Each
of these is a test, because the failure mode is silent: a duplicated listener inflates evidence, and
a stale response attributes a rejection to the wrong session.

### Human observation (CG-015)

`WAITING_FOR_HUMAN -> ROUND_CHANGED -> WAITING_FOR_HUMAN -> DISAPPEARED`, all on **one** session. A
new round never restarts the session; only a removal followed much later by an independent challenge
could justify a second one, and that is the host's call.

`DISAPPEARED` never becomes success. The library says the challenge is no longer present; the host
decides what that means.

A timeout waiting for a human yields `UNKNOWN` with reason `human_observation_timeout` — never
`PROVIDER_REJECTED`, because nothing was rejected.

## Consequences

- Unknown response text stays conservative: with insufficient challenge evidence the outcome is
  `OBSERVE`/`UNKNOWN`. There is no textual approximation path to `PROVIDER_REJECTED`.
- Corroboration is per source, not per signal: one observer contributes at most one vote, so fifteen
  DOM matches are not fifteen proofs while DOM + frames + network are three.
- Two defects were found by the browser fixture rather than by review: the DOM observer read markers
  written inside inline JavaScript (a false positive that never disappeared, since the script text
  outlives the widget), and the fingerprint's forbidden-word list rejected the real class
  `rc-imageselect-tile` as if it were challenge content. Both are fixed and covered.
