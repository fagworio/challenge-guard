"""CG-027/CG-031 — `acao terminou != challenge resolvido`.

A tabela de validacao e o coracao do guard: e ela que impede o executor (ou o
host, ou o browser) de declarar resolucao sem observacao nova.
"""

from __future__ import annotations

import pytest

from challenge_guard import ChallengeObservation, ChallengePhase, ChallengeType
from challenge_guard.resolution.validator import validate_not_premature, validate_progress


def _challenge(detected: bool = True, challenge_type: ChallengeType = ChallengeType.CHECKBOX) -> ChallengeObservation:
    return ChallengeObservation(
        detected=detected,
        phase=ChallengePhase.PRE_SUBMIT,
        challenge_type=challenge_type if detected else ChallengeType.UNKNOWN,
        visible=detected,
        confidence=0.9 if detected else 0.0,
    )


def test_no_previous_challenge_means_there_is_nothing_to_resolve():
    result = validate_progress(previous=None, current=_challenge(detected=False))
    assert result.resolved is False
    assert result.reason_token == "challenge_absent"


def test_still_detected_is_not_progress_even_after_a_write():
    """O caso que o executor erra: a acao terminou, o desafio continua la."""
    result = validate_progress(
        previous=_challenge(),
        current=_challenge(),
        browser_write_sent=True,
    )
    assert result.resolved is False
    assert result.progressed is False
    assert result.write_seen is True, "a escrita e registrada e DESCARTADA como prova"
    assert result.reason_token == "challenge_detected_interactive"


def test_a_non_interactive_challenge_still_present_is_not_progress_either():
    result = validate_progress(
        previous=_challenge(challenge_type=ChallengeType.INVISIBLE),
        current=_challenge(challenge_type=ChallengeType.INVISIBLE),
    )
    assert result.resolved is False
    assert result.reason_token == "challenge_observed_non_interactive"


def test_detected_then_absent_is_real_progress():
    result = validate_progress(previous=_challenge(), current=_challenge(detected=False))
    assert result.progressed is True
    assert result.resolved is True
    assert result.reason_token == "challenge_resolved_externally"


def test_a_provider_confirmation_closes_the_challenge_question():
    result = validate_progress(
        previous=_challenge(),
        current=_challenge(),
        submission_confirmed=True,
    )
    assert result.resolved is True
    assert result.reason_token == "submission_confirmed_overrides_challenge"


def test_resolution_cannot_be_claimed_without_a_fresh_observation():
    with pytest.raises(ValueError, match="fresh observation"):
        validate_not_premature(claimed_resolved=True, current=None)


def test_resolution_cannot_be_claimed_while_the_challenge_is_visible():
    with pytest.raises(ValueError, match="still observed"):
        validate_not_premature(claimed_resolved=True, current=_challenge(), previous=_challenge())


def test_resolution_requires_that_a_challenge_was_observed_before():
    with pytest.raises(ValueError, match="WAS observed"):
        validate_not_premature(claimed_resolved=True, current=_challenge(detected=False), previous=None)
    with pytest.raises(ValueError, match="WAS observed"):
        validate_not_premature(
            claimed_resolved=True, current=_challenge(detected=False), previous=_challenge(detected=False)
        )


def test_a_correct_claim_passes():
    validate_not_premature(claimed_resolved=True, current=_challenge(detected=False), previous=_challenge())


def test_a_non_claim_is_always_allowed():
    validate_not_premature(claimed_resolved=False, current=_challenge(), previous=None)
