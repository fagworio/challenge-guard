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

O monitor aceita um browser opcional e compoe os observadores por dentro. Sem browser o
nucleo continua puro: o adapter do Playwright so e importado quando um browser e de fato
fornecido, entao `import challenge_guard` nunca puxa uma dependencia opcional.

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
| CG-012 | challenge network requirements (describe, never authorise) | done |
| CG-013 | evidence redaction (allowlist, property-tested) | done |
| CG-014 | Playwright adapter (optional extra, thin) | done |
| CG-015 | human observation lifecycle | done |
| CG-015A | passive provider reconnaissance, real fixtures, registry gate | done |
| CG-018 | HumanHandoff (neutral, host enriches) | done |
| CG-019 | public API: `ChallengeMonitor` and a small surface | done |
| CG-020 | release v0.1.0 (wheel proven in an empty environment) | done |
| CG-021 | no browser dependency is added; the launcher stays with the host (ADR 0007) | done |
| CG-022 | `PlaywrightCdpSession` (start/reset/close, ownership explicit) | done |
| CG-023 | CDP -> Playwright bridge reusing the existing adapter | done |
| CG-024 | `ChallengeMonitor.attach_adapter` (explicit backend) | done |
| CG-025 | `ChallengeRuntime` + `ChallengeRuntimeResult` | done |
| CG-026 | Browser lifecycle guard (start/attach/reset/detach/close) | done |
| CG-027 | Observation guard (the browser reports facts, never a decision) | done |
| CG-028 | Network scope guard (challenge read != upload != submission) | done |
| CG-029 | Sensitive material guard (keys, values, journal, result, repr) | done |
| CG-030 | Resolution budget guard (rounds, wait timeout, duration) | done |
| CG-031 | Submission isolation guard (the guard cannot submit) | done |
| CG-032 | Capability guard (`observe_only` .. `unsupported`, never "solved") | done |
| CG-033 | Provenance guard (closed journal, safe reconstruction) | done |
| CG-034 | Architecture guard in CI (AST + selfcheck of the guards) | done |
| CG-035 | E2E: the same decision with Playwright direct and over CDP | done |
| CG-036 | `jobsearch-agent` uses the public runtime | done in the host |
| CG-038 | release 0.2.0 (wheel proven in an empty environment) | done |
| CG-039 | capability-aware timeout (`provider_supported` never becomes human by timeout) | done |
| CG-037 | remove the duplicated `challenge_resolution` in the host | **deferred** |
| CG-016, CG-017 | visual classifier and its privacy gate | **deferred** |

CG-016/CG-017 are deferred deliberately. The visual classifier would only earn its
place if it fixed a case that is currently misclassified, and the reconnaissance showed the
structural observers already carry the real cases. Adding vision now would widen the
privacy surface (screenshots) without a demonstrated benefit. The boundary is already
written down in [ADR 0003](docs/adr/0003-visual-observation-boundary.md), so the first
implementation has a shape to fit whenever it is justified.

## Browser backends: the guard connects, the host launches

The guard does not launch a browser and does not depend on one. It observes a page — and a page can
come from a browser started by anybody, as long as a CDP endpoint is reachable:

```text
host launcher                        endpoint                    guard
SeleniumBase sb_cdp.Chrome()   ->    http://127.0.0.1:<port>  ->  PlaywrightCdpSession
Chrome --remote-debugging-port ->    http://127.0.0.1:<port>  ->    -> Page
Playwright launch              ->    (no endpoint needed)     ->    -> PlaywrightChallengeAdapter
                                                                     -> ChallengeMonitor
```

One observer, one policy, one result. `tools/measure_backends.py` measures the same fixture on every
available launcher and fails if the decision differs; the capture is in
[docs/evidence](docs/evidence/2026-09-25-backend-parity.md). That measurement is **backend parity
certification** — not real-challenge certification: no third-party Cloudflare/reCAPTCHA/hCaptcha, no
real ATS board and no provider acceptance were exercised.

Why `seleniumbase` is **not** a dependency: its CDP Mode is documented by its own authors as *a
stealth mode*, and the Playwright integration as *Stealthy Playwright Mode*. This library's contract
is that it never hides automation signals, so the launcher stays in the host where that choice
belongs. See [ADR 0007](docs/adr/0007-cdp-neutral-browser-and-host-launcher.md).

```python
from challenge_guard import CdpEndpoint, ChallengeRuntime, PlaywrightCdpSession

runtime = ChallengeRuntime(session=PlaywrightCdpSession.from_endpoint(CdpEndpoint.from_url("http://127.0.0.1:9222")))
with runtime:
    runtime.start()
    page = runtime.session.page      # the HOST navigates; the guard only observes
    ...
    decision = runtime.evaluate()
    result = runtime.result()
```

## Guards

Each guard answers a question that must not depend on the discipline of whoever writes the next
commit. Some run at runtime; others are AST checks in CI, because the defect they prevent is
structural.

| Guard | Prevents | Checked by |
| --- | --- | --- |
| lifecycle | duplicate listener, stale adapter, page reused after close, navigation without reset | `guards/lifecycle.py` + tests |
| observation | the browser layer naming a decision (`needs_human`, `decide`, policy) | AST, `tests/unit/test_architecture_guards.py` |
| network scope | submission/upload traffic treated as challenge traffic | `guards/network_scope.py` + tests |
| sensitive material | token/cookie/sitekey/answer in models, journal, result, exceptions, `repr` | `guards/sensitive_material.py` + tests |
| submission isolation | any call or name that could submit, click, type, navigate or POST | AST + CI job |
| capability | a capability value implying the guard solves the challenge | `resolution/capabilities.py` + tests |
| budget | an endless observation loop | `resolution/limits.py` + tests |
| validation | "the action finished" accepted as "the challenge is resolved" | `resolution/validator.py` + tests |
| provenance | audit with a secret in it, or with an invented timestamp | `guards/provenance.py` + tests |
| dependency isolation | `import challenge_guard` pulling Playwright or SeleniumBase | subprocess probe + CI job |

## Real-world fixtures

`tools/passive_recon.py` observes a public board without clicking, filling or submitting, and writes
a sanitised capture to `tests/fixtures/real_world/`. Those captures are replayed offline — fixture to
observers to signals to policy — with no browser and no network, so real discovery becomes a
regression test.

| Provider | Captures | Verified |
| --- | --- | --- |
| hCaptcha | 1 | yes |
| reCAPTCHA | 1 | yes |
| reCAPTCHA Enterprise | 1 | yes |
| generic (Turnstile) | 0 | **no — not claimed** |

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
pip install challenge-guard[playwright]  # the CDP bridge (it is Playwright)
```

`seleniumbase` is deliberately **not** an extra here: the launcher belongs to the host
([ADR 0007](docs/adr/0007-cdp-neutral-browser-and-host-launcher.md)).

The Playwright adapter lives in `challenge_guard.browser` and is not exported from the package root,
so importing `challenge_guard` never pulls Playwright in.

## Development

```bash
pytest -q                       # core suite, no browser
pytest -q tests/integration     # needs the extra and Chromium
python tools/measure_backends.py
```

Browser tests need the optional extra and skip without it:

```bash
pip install -e ".[playwright]" && playwright install chromium
PYTHONPATH=src pytest tests/integration
```

## License

MIT
