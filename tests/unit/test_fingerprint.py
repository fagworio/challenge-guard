"""Fingerprint estrutural (CG-005): detectar mudanca sem olhar conteudo."""

from __future__ import annotations

import pytest

from challenge_guard import (
    ChallengeObservation,
    ChallengePhase,
    ChallengeProvider,
    ChallengeType,
    structural_fingerprint,
)
from challenge_guard.fingerprint import UnsafeFingerprintInput


def _observation(**overrides):
    data = {
        "detected": True,
        "phase": ChallengePhase.PRE_SUBMIT,
        "provider": ChallengeProvider.RECAPTCHA,
        "challenge_type": ChallengeType.IMAGE_SELECTION,
        "dom_signals": ("recaptcha-container", "grid"),
        "frame_signals": ("www.google.com/recaptcha",),
        "challenge_dimensions": (300, 400),
        "confidence": 0.9,
    }
    data.update(overrides)
    return ChallengeObservation(**data)


def test_no_challenge_has_no_fingerprint():
    """Fingerprint de 'nada' nao pode ser comparavel com o de uma rodada real."""
    assert structural_fingerprint(_observation(detected=False)) == ""


def test_same_structure_gives_the_same_fingerprint():
    assert structural_fingerprint(_observation()) == structural_fingerprint(_observation())


def test_signal_order_is_not_structure():
    first = structural_fingerprint(_observation(dom_signals=("grid", "recaptcha-container")))
    second = structural_fingerprint(_observation(dom_signals=("recaptcha-container", "grid")))
    assert first == second


def test_new_grid_is_a_new_round():
    before = structural_fingerprint(_observation(dom_signals=("recaptcha-container", "grid-3x3")))
    after = structural_fingerprint(_observation(dom_signals=("recaptcha-container", "grid-4x4")))
    assert before != after


def test_swapped_iframe_is_a_new_round():
    before = structural_fingerprint(_observation(frame_signals=("www.google.com/recaptcha",)))
    after = structural_fingerprint(_observation(frame_signals=("www.recaptcha.net/recaptcha",)))
    assert before != after


def test_dimension_change_is_a_new_round():
    before = structural_fingerprint(_observation(challenge_dimensions=(300, 400)))
    after = structural_fingerprint(_observation(challenge_dimensions=(420, 560)))
    assert before != after


def test_provider_and_type_participate():
    assert structural_fingerprint(_observation()) != structural_fingerprint(
        _observation(provider=ChallengeProvider.HCAPTCHA)
    )
    assert structural_fingerprint(_observation()) != structural_fingerprint(
        _observation(challenge_type=ChallengeType.CHECKBOX)
    )


def test_real_structure_class_names_are_accepted():
    """Falso positivo derruba a observacao: classes reais nao podem ser recusadas."""
    for structural in ("rc-imageselect-tile", "rc-imageselect-click", "grid-4x4", "data-sitekey"):
        assert structural_fingerprint(_observation(dom_signals=(structural,)))


def test_challenge_content_is_refused_loudly():
    """Um observador que traga conteudo do desafio nao pode ser ignorado em silencio."""
    # Exemplos inequivocamente de CONTEUDO. `tile`/`click` saem da lista: classes
    # reais como `rc-imageselect-tile` sao estrutura, nao resposta.
    for signal in ("cf-turnstile-response-token", "selected-answer-3", "solution-row-2", "authorization: bearer"):
        with pytest.raises(UnsafeFingerprintInput):
            structural_fingerprint(_observation(dom_signals=(signal,)))


def test_network_and_response_signals_never_enter_the_fingerprint():
    """Duas rodadas identicas em estrutura sao a mesma rodada, mesmo que a rede mude."""
    before = structural_fingerprint(_observation())
    after = structural_fingerprint(
        _observation(
            network_signals=("POST hcaptcha.com/getcaptcha",),
            response_signals=("verification failed",),
        )
    )
    assert before == after


def test_fingerprint_is_short_and_stable_across_runs():
    value = structural_fingerprint(_observation())
    assert len(value) == 32
    assert value == value.lower()
    int(value, 16)  # hexadecimal valido
