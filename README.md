# challenge-guard

Detects, observes and classifies anti-bot challenges. **Never solves them.**

The library answers one question: *has the automation reached a boundary that requires a human?*
It reports; the host decides. It has no knowledge of ATS vendors, boards, jobs, resumes or
candidates — only of challenge technologies.

```python
from challenge_guard import (
    ChallengeObservation,
    ChallengePhase,
    ChallengePolicy,
    ChallengeProvider,
    ChallengeSessionTracker,
    ChallengeType,
)

tracker = ChallengeSessionTracker()
policy = ChallengePolicy()

observation = ChallengeObservation(
    detected=True,
    phase=ChallengePhase.PRE_SUBMIT,
    provider=ChallengeProvider.HCAPTCHA,
    challenge_type=ChallengeType.IMAGE_SELECTION,
    visible=True,
    confidence=0.9,
)

session = tracker.start(observation)
decision = policy.decide(observation, session)

assert decision.status.value == "needs_human"
assert decision.human_required is True
# O guard pede a pessoa e continua observando — nunca interage com o desafio.
```

A `ChallengeMonitor` conveniente para o host chega em CG-019; hoje a API publica e o
dominio puro, sem dependencia de browser.

## What it will never do

```text
select CAPTCHA images          compute which tiles to click
click challenges               answer challenges
generate or inject tokens      reuse tokens
hide navigator.webdriver       alter fingerprints
spoof plugins                  proxy to raise reputation
simulate human behaviour to fool anti-bot
```

These operations do not exist in the API, and adding one would defeat the library's purpose. See
[ADR 0001](docs/adr/0001-challenge-boundary.md).

## Status

Roadmap CG-001 .. CG-006 are implemented:

| Item | Scope | State |
| --- | --- | --- |
| CG-001 | package, CI, tests | done |
| CG-002 | domain model (no browser dependency) | done |
| CG-003 | session lifecycle and round tracking | done |
| CG-004 | session state machine (invalid transitions raise) | done |
| CG-005 | structural fingerprinting | done |
| CG-006 | policy engine and precedence rules | done |
| CG-007 | DOM observer (structure only) | done |
| CG-008 | frame observer (host and shape) | done |
| CG-009 | network observer (redacted metadata) | done |
| CG-010 | response observer (phrase to concept) | done |
| CG-011 | provider registry (hCaptcha, reCAPTCHA, Enterprise, generic) | done |
| CG-012 .. CG-020 | network requirements, evidence, Playwright, vision, handoff, release | pending |

## Precedence rules

The order in `policy.py` **is** the specification:

1. A confirmed submission is never downgraded by a leftover CAPTCHA widget.
2. Disappearance is `RESOLVED_EXTERNALLY` — never success.
3. A submission write plus anti-bot evidence is `PROVIDER_REJECTED`.
4. A write with no decisive evidence is only `OBSERVE`: a widget alone does not prove rejection.
5. An interactive challenge before any write is `NEEDS_HUMAN`.
6. A non-interactive challenge (`invisible`, `risk_assessment`) is only observed — it may clear by
   itself, and demanding a person would be a false positive.
7. A non-interactive challenge that the provider explicitly demanded is escalated anyway: the
   server said a challenge is required.
8. Weak detection is `UNKNOWN`. A status code alone never classifies CAPTCHA.

## How a decision is reached

Observers see concrete things; the policy only sees concepts.

```text
raw response
  -> ResponseObserver
  -> provider profile      # the only place concrete phrases live
  -> ChallengeSignal(kind=VERIFICATION_REJECTED, source="response")
  -> policy
  -> PROVIDER_REJECTED
```

`policy.py` is asserted to contain no provider phrase and no vendor name, so provider vocabulary
cannot creep back into the decision logic. Provider data lives in `providers/registry.py`, which is
asserted to contain no ATS vendor — source included, comments included.

## Install

```bash
pip install challenge-guard            # core, no browser dependency
pip install challenge-guard[playwright]
```

## Development

```bash
PYTHONPATH=src pytest
```

## License

MIT
