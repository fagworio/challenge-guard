"""Modelo de dominio (CG-002): vocabulario e validacoes."""

from __future__ import annotations

import pytest

from challenge_guard import (
    ChallengeDecision,
    ChallengeDecisionStatus,
    ChallengeObservation,
    ChallengePhase,
    ChallengeProvider,
    ChallengeRoundObservation,
    ChallengeType,
    ReasonToken,
)


def test_providers_are_challenge_technologies_not_ats_vendors():
    """O guard nao conhece ATS: so tecnologias de challenge."""
    names = {provider.value for provider in ChallengeProvider}
    assert names == {
        "unknown",
        "recaptcha",
        "recaptcha_enterprise",
        "hcaptcha",
        "turnstile",
        "generic",
    }
    for vendor in ("greenhouse", "lever", "ashby", "workable", "ciandt", "canonical"):
        assert vendor not in names


def test_phases_cover_the_whole_host_flow():
    assert {phase.value for phase in ChallengePhase} == {
        "page_load",
        "form_discovery",
        "form_fill",
        "pre_submit",
        "submitting",
        "post_submit",
    }


@pytest.mark.parametrize(
    "challenge_type",
    [ChallengeType.CHECKBOX, ChallengeType.IMAGE_SELECTION, ChallengeType.TEXT, ChallengeType.MATH, ChallengeType.PUZZLE],
)
def test_interactive_types_require_a_person(challenge_type):
    assert challenge_type.interactive is True


@pytest.mark.parametrize(
    "challenge_type",
    [ChallengeType.INVISIBLE, ChallengeType.RISK_ASSESSMENT, ChallengeType.UNKNOWN],
)
def test_non_interactive_types_never_demand_a_person(challenge_type):
    """Um selo invisivel que se resolve sozinho nao pode virar 'precisa humano'."""
    assert challenge_type.interactive is False


def test_type_names_describe_observation_not_a_plan_to_solve():
    forbidden = {"solved", "solution", "answer", "bypass", "token"}
    assert forbidden.isdisjoint({item.value for item in ChallengeType})


def test_observation_rejects_impossible_values():
    with pytest.raises(ValueError):
        ChallengeObservation(detected=True, phase=ChallengePhase.PAGE_LOAD, confidence=1.4)
    with pytest.raises(ValueError):
        ChallengeObservation(detected=True, phase=ChallengePhase.PAGE_LOAD, http_status=99)
    with pytest.raises(ValueError):
        ChallengeObservation(detected=True, phase=ChallengePhase.PAGE_LOAD, http_status=700)


def test_observation_reports_which_observers_contributed():
    observation = ChallengeObservation(
        detected=True,
        phase=ChallengePhase.PRE_SUBMIT,
        dom_signals=(".h-captcha",),
        frame_signals=("hcaptcha.com",),
        response_signals=("please complete",),
    )
    assert observation.evidence_sources == ("dom", "frames", "response")


def test_round_observation_validates_its_numbers():
    with pytest.raises(ValueError):
        ChallengeRoundObservation("s1", 0, "now", True, False, "abc", 0.9)
    with pytest.raises(ValueError):
        ChallengeRoundObservation("s1", 1, "now", True, False, "abc", 2.0)


def test_decision_refuses_a_reason_token_outside_the_closed_set():
    """Motivo e conjunto fechado: e o que sobrevive a redacao."""
    with pytest.raises(ValueError):
        ChallengeDecision(status=ChallengeDecisionStatus.UNKNOWN, reason_token="porque_sim")
    decision = ChallengeDecision(
        status=ChallengeDecisionStatus.NEEDS_HUMAN,
        reason_token=ReasonToken.CHALLENGE_DETECTED_PRE_SUBMIT.value,
    )
    assert decision.reason_token == "challenge_detected_pre_submit"


def test_every_reason_token_is_short_and_free_of_content():
    for token in ReasonToken:
        assert token.value.islower()
        assert " " not in token.value
        for forbidden in ("token", "cookie", "answer", "solution"):
            assert forbidden not in token.value
