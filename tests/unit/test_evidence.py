"""CG-013: a evidencia nao pode carregar payload, token nem PII."""

from __future__ import annotations

import json

import pytest

from challenge_guard import (
    ChallengeEvidence,
    ChallengeObservation,
    ChallengePhase,
    ChallengePolicy,
    ChallengeProvider,
    ChallengeSessionTracker,
    ChallengeType,
    ChallengeSignal,
    ChallengeSignalKind,
    EvidenceLeak,
    redact,
)

#: Payloads que NUNCA podem sobreviver a redacao.
SENTINELS = (
    "cf-turnstile-response-SENTINEL",
    "hcaptcha-token-SENTINEL",
    "sitekey-SENTINEL",
    "cookie-SENTINEL",
    "authorization-SENTINEL",
    "candidate@example.com",
    "+5531999999999",
    "form-value-SENTINEL",
)


def _observation(**overrides):
    data = {
        "detected": True,
        "phase": ChallengePhase.PRE_SUBMIT,
        "provider": ChallengeProvider.HCAPTCHA,
        "challenge_type": ChallengeType.IMAGE_SELECTION,
        "confidence": 0.9,
        "http_status": 400,
    }
    data.update(overrides)
    return ChallengeObservation(**data)


def test_evidence_has_an_allowlist_shape():
    """O que nao esta declarado nao entra: uma denylist sempre esquece um campo."""
    tracker = ChallengeSessionTracker()
    observation = _observation()
    session = tracker.start(observation)
    decision = ChallengePolicy().decide(observation, session)
    evidence = redact(session=session, observation=observation, decision=decision)
    assert set(evidence.to_dict()) == {
        "session_id",
        "provider",
        "phase",
        "decision",
        "reason_token",
        "sources",
        "signal_kinds",
        "http_status",
        "path_hashes",
        "rounds_observed",
        "confidence",
    }


def test_a_sentinel_in_dom_signals_is_refused_even_before_redaction():
    """Defesa em profundidade: o fingerprint recusa conteudo antes da evidencia."""
    from challenge_guard.fingerprint import UnsafeFingerprintInput

    observation = _observation(dom_signals=("captcha-response-token-SENTINEL",))
    with pytest.raises(UnsafeFingerprintInput):
        ChallengeSessionTracker().start(observation)


def test_serialized_evidence_never_contains_a_sentinel():
    """Teste de propriedade: serializa tudo e procura payload sentinela."""
    tracker = ChallengeSessionTracker()
    observation = _observation(
        network_signals=SENTINELS,
        response_signals=SENTINELS,
    )
    session = tracker.start(observation)
    decision = ChallengePolicy().decide(observation, session)
    blob = json.dumps(redact(session=session, observation=observation, decision=decision).to_dict())
    for sentinel in SENTINELS:
        assert sentinel not in blob, f"{sentinel} leaked into evidence"
    assert "SENTINEL" not in blob
    assert "@" not in blob


def test_raw_signals_never_reach_the_evidence():
    """Nem os sinais do observer: so os conceitos."""
    observation = _observation(
        signals=(
            ChallengeSignal(
                kind=ChallengeSignalKind.CHALLENGE_VISIBLE,
                source="dom",
                provider=ChallengeProvider.HCAPTCHA,
                confidence=0.8,
                detail="dom.h-captcha",
            ),
        )
    )
    evidence = redact(
        session=None,
        observation=observation,
        decision=ChallengePolicy().decide(observation),
    )
    assert evidence.signal_kinds == ("challenge_visible",)
    assert "h-captcha" not in json.dumps(evidence.to_dict())


def test_path_hashes_must_be_opaque():
    with pytest.raises(EvidenceLeak):
        ChallengeEvidence(
            session_id="s1",
            provider="hcaptcha",
            phase="pre_submit",
            decision="observe",
            reason_token="challenge_absent",
            path_hashes=("/getcaptcha/segredo",),
        )


def test_forbidden_content_is_refused_even_in_allowed_fields():
    for bad in ("token-abc", "sitekey-abc", "cookie-abc", "user@example.com", "candidate-1"):
        with pytest.raises(EvidenceLeak):
            ChallengeEvidence(
                session_id=bad,
                provider="hcaptcha",
                phase="pre_submit",
                decision="observe",
                reason_token="challenge_absent",
            )


def test_sources_and_kinds_must_be_short_tokens():
    with pytest.raises(EvidenceLeak):
        ChallengeEvidence(
            session_id="s1",
            provider="hcaptcha",
            phase="pre_submit",
            decision="observe",
            reason_token="challenge_absent",
            sources=("dom with a whole sentence attached",),
        )
    with pytest.raises(EvidenceLeak):
        ChallengeEvidence(
            session_id="s1",
            provider="hcaptcha",
            phase="pre_submit",
            decision="observe",
            reason_token="challenge_absent",
            signal_kinds=("a" * 100,),
        )


def test_impossible_values_are_refused():
    with pytest.raises(EvidenceLeak):
        ChallengeEvidence(
            session_id="s1", provider="hcaptcha", phase="pre_submit",
            decision="observe", reason_token="challenge_absent", http_status=42,
        )
    with pytest.raises(EvidenceLeak):
        ChallengeEvidence(
            session_id="s1", provider="hcaptcha", phase="pre_submit",
            decision="observe", reason_token="challenge_absent", confidence=2.0,
        )
    with pytest.raises(EvidenceLeak):
        ChallengeEvidence(
            session_id="s1", provider="hcaptcha", phase="pre_submit",
            decision="observe", reason_token="challenge_absent", rounds_observed=-1,
        )


def test_path_hashes_are_extracted_from_network_signals_only():
    observation = _observation(
        signals=(
            ChallengeSignal(
                kind=ChallengeSignalKind.CHALLENGE_TRAFFIC,
                source="network",
                provider=ChallengeProvider.HCAPTCHA,
                confidence=0.7,
                detail="net.hcaptcha.0123456789abcdef",
            ),
        )
    )
    evidence = redact(
        session=None,
        observation=observation,
        decision=ChallengePolicy().decide(observation),
        path_hashes=("0123456789abcdef",),
    )
    assert evidence.path_hashes == ("0123456789abcdef",)
