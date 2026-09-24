# ADR 0001: challenge boundary

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

The jobsearch-agent drives real application forms. Three of the four ATS platforms it supports
protect submissions with a CAPTCHA, and the protection is platform-wide, not per board: the same
hCaptcha key appears on two unrelated Lever boards, and the same reCAPTCHA key on two unrelated
Ashby boards. With the decision not to disguise automation, those boards cannot be submitted
automatically.

That knowledge was living inside the submission code as `_captcha_visible()`, `_captcha_demanded()`
and a marker tuple — provider anti-bot intelligence embedded in the ATS layer. Three providers were
about to grow three different versions of the same problem.

## Decision

Extract a separate library, `challenge-guard`, whose only job is to answer one question: **has the
automation reached a boundary that requires a human?** It detects, observes, classifies, tracks the
lifecycle and produces evidence.

It never solves. The following do not exist in the API, and must not be added:

```text
selecting CAPTCHA images        computing which tiles to click
clicking challenges             answering challenges
generating or injecting tokens  reusing tokens
hiding navigator.webdriver      altering fingerprints
spoofing plugins                using a proxy to raise reputation
simulating human behaviour to fool anti-bot
```

The absence is the contract, not a side note. A function that resolves a challenge would mean the
library now decides whether a security mechanism should believe the human is the agent — which is
the opposite of what it is for. Tests assert the vocabulary itself contains no `solve`, `answer`,
`bypass`, `token` or `stealth`.

The library knows challenge technologies (`recaptcha`, `recaptcha_enterprise`, `hcaptcha`,
`turnstile`, `generic`) and never ATS vendors, boards, jobs, resumes or candidates. A test asserts no
vendor name appears in the provider enum.

## Consequences

- The host keeps ownership of application state, submission intents and network authorization. The
  guard reports; the host decides.
- There is no `SUCCESS` status. The closest outcome is `RESOLVED_EXTERNALLY`: the challenge went
  away, and whether the flow may continue is the host's call, never the guard's claim.
- The guard may report that a human is required. That is the full extent of its authority.
