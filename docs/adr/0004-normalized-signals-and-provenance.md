# ADR 0004: normalized signals and provenance

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

The first cut of the policy engine recognised rejection by scanning response text against a tuple of
phrases living inside `policy.py`:

```python
_REJECTION_MARKERS = ("please complete the recaptcha", "verifying your application", ...)
```

That put provider vocabulary — concrete strings observed on real boards — into the domain rule. It
also meant a new provider, or a wording change by an existing one, required editing the decision
logic. The domain would slowly fill with the vocabulary of individual anti-bot vendors, which is the
same coupling this library exists to remove, one layer up.

Discovery also produced heterogeneous output: the DOM observer saw markers, the frame observer saw
hosts, the network observer saw paths, the response observer saw text. The policy would have needed
to know all four shapes.

## Decision

Observers emit **normalized signals with provenance**:

```python
ChallengeSignal(
    kind=ChallengeSignalKind.VERIFICATION_REJECTED,
    source="response",
    provider=ChallengeProvider.HCAPTCHA,
    confidence=0.95,
    detail="error_verifying_application",
)
```

The flow becomes:

```text
raw response
  -> ResponseObserver
  -> provider profile      (concrete phrases live here, and only here)
  -> ChallengeSignal       (a concept)
  -> policy                (concept in, decision out)
```

1. `ChallengeSignalKind` is a closed set of *concepts* the policy may reason about:
   `challenge_visible`, `challenge_traffic`, `challenge_required`, `verification_rejected`,
   `risk_assessment_only`.
2. Concrete phrases, hosts and structural markers live in declarative provider profiles
   (`providers/registry.py`). That registry contains no ATS vendor — enforced by a test that also
   scans the file's source, so even a comment naming a board fails the build.
3. `detail` must be a short controlled token, never provider text. A free-form field would become,
   in practice, somewhere to dump payload into the audit trail. Validated in `__post_init__`.
4. `ChallengeObservation.signals` carries the normalized result. `policy.py` is asserted to contain
   no provider phrase and no vendor name, so the old marker tuple cannot creep back.
5. One observer emits at most **one** signal per provider per observation. Several markers matching
   is corroboration of the same observation, not independent evidence; one signal per marker would
   inflate confidence without anything more having been seen.

Two refinements landed with it:

- **Knowledge is monotonic unless contradicted by stronger evidence.** A blind round (`UNKNOWN`)
  never erases a known provider, and replacing a known provider requires *higher* confidence than
  the round that established it. A test covers each direction.
- **Phase plus observed effect.** An invisible challenge at `PAGE_LOAD` that blocks nothing stays
  `OBSERVE`; the same type at `SUBMITTING` with an unequivocal anti-bot rejection becomes
  `PROVIDER_REJECTED`. An explicit `challenge_required` from the provider escalates regardless of the
  observed type, because the server said so. This avoids both errors: demanding a person too early,
  and letting a real 400/428 through.

## Consequences

- Adding a provider is a data change in the registry, not a change to the decision logic.
- The provenance of every signal is recorded (`source`), so an audit can say *why* a decision was
  reached without storing what the provider actually said.
- Because the policy is phrase-free, a test can assert it stays that way — the invariant is
  mechanical rather than a review convention.
- Ambiguity is preserved rather than resolved by guessing: when two providers match the same DOM
  evidence, both signals are emitted. `reCAPTCHA Enterprise` deliberately declares no DOM markers,
  since it is invisible and the response is what distinguishes it.
