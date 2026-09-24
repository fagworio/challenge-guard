# ADR 0006: passive provider reconnaissance

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

CG-007 to CG-015 built the observers, the registry and the browser adapter, but the registry's
provider data was largely recall and inference from three rejection messages. Before integrating
with the host, that inference needed to meet reality.

`tools/passive_recon.py` observes a public board's anti-bot surface without clicking, filling or
submitting anything. It records structural DOM, frames (host and normalised path) and network
metadata (origin, hashed path, method, resource type, status), and nothing else. One capture per
provider was taken and turned into a sanitised fixture under `tests/fixtures/real_world/`.

## Findings

### The frame path discriminates providers that share a host

The same `www.recaptcha.net` serves `/recaptcha/enterprise/anchor` on one board and
`/recaptcha/api2/anchor` on another. The registry matched on host alone, so the first profile in
order won and **reCAPTCHA Enterprise was never identified** — which changed the observed type and,
with it, the decision. Profiles now declare `frame_paths`, `profile_for_frame` resolves host plus
path, and a path-specific match is weighted above a generic DOM marker, since it is the more
specific evidence.

### The frame path can carry the provider's account token

A real capture showed `/captcha/v1/<se-token>/static/hcaptcha-enclave.html`: the hCaptcha account
token travels **in the path**. Recording frame paths literally would leak the identifier and, worse,
would make the structural fingerprint change whenever the provider rotates the id — inventing a new
round with nothing structurally different. `path_shape` replaces opaque segments with `:id`, and the
observer records the shape, not the literal path.

### Other corrections

- Runtime origins were incomplete: `apis.google.com` and `content.googleapis.com` are used by the
  reCAPTCHA widget and were missing from the declaration.
- hCaptcha serves dynamic per-session subdomains (`<hash>.w.hcaptcha.com`). Covered by the existing
  wildcard, and a reminder that the wildcard-requires-a-path rule earns its keep.
- A `title` attribute carried embedded markup containing a token. Attribute *presence* is the
  structural fact; the value is now redacted.
- DOM detection is weak for these providers: the widget lives in a cross-origin iframe, so frames
  and network carry the detection in every capture. This is recorded rather than papered over.

### Rejection markers were deliberately not validated here

`There was an error verifying your application` and `Please complete the reCAPTCHA` only appear after
a submission flow. Reproducing a rejection just to confirm the wording would mean submitting
something. Those markers keep `EvidenceLevel.OBSERVED` from the earlier real submissions and were not
re-derived.

## Decision

1. Correct the registry from observation, not from further inference.
2. Ship the captures as sanitised fixtures and replay them offline: fixture to observers to signals
   to policy, with no browser and no network. Real discovery becomes an offline regression.
3. Add a registry gate: every provider claiming real-world support must have at least one real
   structural capture, and recognition must not depend on any `INFERRED` marker. `GENERIC` is
   explicitly **not** claimed as verified — there is no Turnstile capture, and admitting the gap is
   better than implying coverage.
4. No further abstraction. The reconnaissance corrects data; it does not redesign.

## Known limitation

Classic reCAPTCHA's v2 checkbox and its v3 badge are indistinguishable from structure alone: both
serve `/recaptcha/api2/anchor`, and both measured 256x60 in the captures. A visible anchor frame is
therefore treated as interactive and yields `NEEDS_HUMAN`, which is conservative: the cost is an
unnecessary human handoff, not a wrong submission. Distinguishing them would require reading the
`render` query parameter, which the privacy boundary forbids recording. Recorded as an open
limitation rather than resolved by a magic size threshold fitted to two samples.
