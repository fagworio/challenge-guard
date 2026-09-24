"""Motor de politica (CG-006): as regras de precedencia."""

from __future__ import annotations

import pytest

from challenge_guard import (
    ChallengeDecisionStatus,
    ChallengeObservation,
    ChallengePhase,
    ChallengePolicy,
    ChallengeProvider,
    ChallengeSessionTracker,
    ChallengeType,
    ReasonToken,
    ResponseObserver,
    ResponseRecord,
)


def _signals(text: str, status: int | None = None):
    """Sinais normalizados a partir de texto de resposta, como em producao."""
    return ResponseObserver().observe([ResponseRecord(status=status, text=text)]).signals


def _observation(**overrides):
    data = {
        "detected": True,
        "phase": ChallengePhase.PRE_SUBMIT,
        "provider": ChallengeProvider.HCAPTCHA,
        "challenge_type": ChallengeType.IMAGE_SELECTION,
        "visible": True,
        "confidence": 0.9,
    }
    text = overrides.pop("response_text", "")
    status = overrides.pop("response_status", None)
    data.update(overrides)
    observation = ChallengeObservation(**data)
    if text:
        from dataclasses import replace

        result = ResponseObserver().observe([ResponseRecord(status=status, text=text)])
        observation = replace(observation, signals=result.signals, provider=result.provider or observation.provider)
    return observation


# --- 1. confirmacao real vence ------------------------------------------------


def test_a_confirmed_submission_is_never_downgraded_by_a_leftover_widget():
    """Uma candidatura aceita nao volta a 'precisa humano' por um iframe no DOM."""
    policy = ChallengePolicy()
    decision = policy.decide(_observation(), None, submission_confirmed=True)
    assert decision.status is ChallengeDecisionStatus.NONE
    assert decision.human_required is False
    assert decision.retry_allowed is False
    assert decision.reason_token == ReasonToken.SUBMISSION_CONFIRMED_OVERRIDES_CHALLENGE.value


def test_confirmation_wins_even_over_a_visible_interactive_widget():
    policy = ChallengePolicy()
    decision = policy.decide(
        _observation(challenge_type=ChallengeType.IMAGE_SELECTION, visible=True),
        None,
        submission_confirmed=True,
    )
    assert decision.status is ChallengeDecisionStatus.NONE


# --- 2. ausencia e desaparecimento --------------------------------------------


def test_no_challenge_at_all_is_not_a_decision_about_captcha():
    decision = ChallengePolicy().decide(_observation(detected=False), None)
    assert decision.status is ChallengeDecisionStatus.NONE
    assert decision.reason_token == ReasonToken.CHALLENGE_ABSENT.value


def test_disappearance_resolves_externally_and_never_claims_success():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.observe(session, _observation(detected=False))
    decision = ChallengePolicy().decide(_observation(detected=False), session)
    assert decision.status is ChallengeDecisionStatus.RESOLVED_EXTERNALLY
    assert decision.human_required is False
    # Nao existe status de sucesso nesta biblioteca: quem valida e o host.
    assert not hasattr(ChallengeDecisionStatus, "SUCCESS")


# --- 3. rejeicao depois da escrita --------------------------------------------


def test_write_sent_plus_anti_bot_evidence_is_a_provider_rejection():
    decision = ChallengePolicy().decide(
        _observation(
            phase=ChallengePhase.POST_SUBMIT,
            browser_write_sent=True,
            http_status=400,
            response_text="There was an error verifying your application. Please try again.",
        ),
        None,
    )
    assert decision.status is ChallengeDecisionStatus.PROVIDER_REJECTED
    assert decision.human_required is True
    assert decision.retry_allowed is False


def test_http_428_with_the_recaptcha_message_is_a_rejection():
    decision = ChallengePolicy().decide(
        _observation(
            phase=ChallengePhase.SUBMITTING,
            browser_write_sent=True,
            http_status=428,
            response_text="Please complete the reCAPTCHA and resubmit your application.",
        ),
        None,
    )
    assert decision.status is ChallengeDecisionStatus.PROVIDER_REJECTED


def test_a_status_code_alone_never_classifies_captcha():
    """HTTP 400 sem evidencia anti-bot e validacao comum, nao CAPTCHA."""
    decision = ChallengePolicy().decide(
        _observation(
            phase=ChallengePhase.POST_SUBMIT,
            browser_write_sent=True,
            http_status=400,
            response_text="Resume/CV is required.",
        ),
        None,
    )
    assert decision.status is ChallengeDecisionStatus.OBSERVE
    assert decision.status is not ChallengeDecisionStatus.PROVIDER_REJECTED


def test_a_widget_after_a_write_without_evidence_is_only_observed():
    """Widget presente nao prova recusa: faltaria a evidencia do provedor."""
    decision = ChallengePolicy().decide(
        _observation(phase=ChallengePhase.POST_SUBMIT, browser_write_sent=True, http_status=200),
        None,
    )
    assert decision.status is ChallengeDecisionStatus.OBSERVE
    assert decision.human_required is False


# --- 4 e 5. interativo versus nao interativo ----------------------------------


@pytest.mark.parametrize(
    "challenge_type",
    [ChallengeType.CHECKBOX, ChallengeType.IMAGE_SELECTION, ChallengeType.TEXT, ChallengeType.MATH, ChallengeType.PUZZLE],
)
def test_an_interactive_challenge_before_any_write_needs_a_human(challenge_type):
    decision = ChallengePolicy().decide(_observation(challenge_type=challenge_type), None)
    assert decision.status is ChallengeDecisionStatus.NEEDS_HUMAN
    assert decision.human_required is True
    assert decision.retry_allowed is True


def test_a_pre_submit_challenge_is_reported_as_such():
    decision = ChallengePolicy().decide(_observation(phase=ChallengePhase.PRE_SUBMIT), None)
    assert decision.reason_token == ReasonToken.CHALLENGE_DETECTED_PRE_SUBMIT.value


def test_an_interactive_challenge_at_another_phase_uses_the_general_token():
    decision = ChallengePolicy().decide(_observation(phase=ChallengePhase.POST_SUBMIT), None)
    assert decision.reason_token == ReasonToken.CHALLENGE_DETECTED_INTERACTIVE.value


def test_an_invisible_badge_does_not_demand_a_person():
    """Selo invisivel pode liberar sozinho: pedir humano seria falso positivo."""
    decision = ChallengePolicy().decide(
        _observation(challenge_type=ChallengeType.INVISIBLE, visible=False), None
    )
    assert decision.status is ChallengeDecisionStatus.OBSERVE
    assert decision.human_required is False


def test_a_risk_assessment_is_observed_not_escalated():
    decision = ChallengePolicy().decide(
        _observation(challenge_type=ChallengeType.RISK_ASSESSMENT), None
    )
    assert decision.status is ChallengeDecisionStatus.OBSERVE


# --- 6. ambiguidade -----------------------------------------------------------


def test_weak_detection_does_not_authorise_a_strong_decision():
    decision = ChallengePolicy().decide(_observation(confidence=0.2), None)
    assert decision.status is ChallengeDecisionStatus.UNKNOWN
    assert decision.reason_token == ReasonToken.CHALLENGE_AMBIGUOUS.value
    assert decision.human_required is False


def test_the_confidence_threshold_is_configurable():
    policy = ChallengePolicy(confidence_threshold=0.95)
    assert policy.decide(_observation(confidence=0.9), None).status is ChallengeDecisionStatus.UNKNOWN
    with pytest.raises(ValueError):
        ChallengePolicy(confidence_threshold=1.5)


# --- sessao -------------------------------------------------------------------


def test_the_provider_falls_back_to_the_session_when_the_round_is_blind():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    decision = ChallengePolicy().decide(
        _observation(provider=ChallengeProvider.UNKNOWN, confidence=0.9), session
    )
    assert decision.provider is ChallengeProvider.HCAPTCHA


def test_every_decision_carries_a_closed_set_reason_token():
    policy = ChallengePolicy()
    decisions = [
        policy.decide(_observation(), None),
        policy.decide(_observation(detected=False), None),
        policy.decide(_observation(browser_write_sent=True, response_text="verification failed"), None),
        policy.decide(_observation(confidence=0.1), None),
        policy.decide(_observation(), None, submission_confirmed=True),
    ]
    for decision in decisions:
        assert decision.reason_token in {token.value for token in ReasonToken}


# --- fase + efeito observado (refinamento) ------------------------------------


def test_an_invisible_challenge_on_page_load_that_blocks_nothing_is_only_observed():
    """Nao pedir humano cedo demais por causa de um selo que talvez se resolva."""
    observation = _observation(
        phase=ChallengePhase.PAGE_LOAD,
        challenge_type=ChallengeType.INVISIBLE,
        visible=False,
        provider=ChallengeProvider.RECAPTCHA_ENTERPRISE,
    )
    decision = ChallengePolicy().decide(observation, None)
    assert decision.status is ChallengeDecisionStatus.OBSERVE
    assert decision.human_required is False


def test_the_same_invisible_challenge_after_a_rejected_write_is_a_rejection():
    """O mesmo tipo, em SUBMITTING e com recusa inequivoca, nao pode passar batido."""
    observation = _observation(
        phase=ChallengePhase.SUBMITTING,
        challenge_type=ChallengeType.INVISIBLE,
        visible=False,
        provider=ChallengeProvider.RECAPTCHA_ENTERPRISE,
        browser_write_sent=True,
        http_status=428,
        response_text="Please complete the reCAPTCHA and resubmit your application.",
    )
    decision = ChallengePolicy().decide(observation, None)
    assert decision.status is ChallengeDecisionStatus.PROVIDER_REJECTED
    assert decision.human_required is True


def test_a_provider_demanding_the_challenge_escalates_even_when_the_type_is_invisible():
    """O pedido explicito do provedor vence o tipo observado."""
    observation = _observation(
        phase=ChallengePhase.PRE_SUBMIT,
        challenge_type=ChallengeType.RISK_ASSESSMENT,
        browser_write_sent=False,
        response_text="Please complete the reCAPTCHA to continue.",
    )
    decision = ChallengePolicy().decide(observation, None)
    assert decision.status is ChallengeDecisionStatus.NEEDS_HUMAN
    assert decision.human_required is True


def test_a_form_error_that_merely_mentions_verification_is_not_a_captcha():
    """Ruido de formulario nao pode virar rejeicao anti-bot."""
    observation = _observation(
        phase=ChallengePhase.POST_SUBMIT,
        browser_write_sent=True,
        http_status=400,
        response_text="Email verification is pending for this account.",
    )
    assert ChallengePolicy().decide(observation, None).status is ChallengeDecisionStatus.OBSERVE
