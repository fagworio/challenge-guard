"""Registry de providers (CG-011), sinais normalizados e pureza da policy."""

from __future__ import annotations

import pathlib

import pytest

from challenge_guard import (
    ChallengeProvider,
    ChallengeSignal,
    ChallengeSignalKind,
    PROFILES,
    profile_for,
    profile_for_host,
    profiles,
)

SOURCE = pathlib.Path(__file__).parents[2] / "src" / "challenge_guard"

#: Nomes de vendors de recrutamento. Se algum aparecer no registry, a
#: inteligencia anti-bot voltou a se acoplar ao board.
ATS_VENDORS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "ciandt", "canonical")


# --- registry -----------------------------------------------------------------


def test_the_four_initial_providers_are_declared():
    declared = {profile.provider for profile in profiles()}
    assert declared == {
        ChallengeProvider.HCAPTCHA,
        ChallengeProvider.RECAPTCHA,
        ChallengeProvider.RECAPTCHA_ENTERPRISE,
        ChallengeProvider.GENERIC,
    }


def test_the_registry_knows_no_ats_vendor():
    for profile in PROFILES:
        blob = " ".join(
            [
                profile.provider.value,
                *profile.frame_hosts,
                *profile.runtime_hosts,
                *profile.dom_markers,
                *profile.widget_hosts,
                *(marker.phrase for marker in profile.response_markers),
            ]
        ).casefold()
        for vendor in ATS_VENDORS:
            assert vendor not in blob, f"{vendor} leaked into the challenge registry"


def test_no_ats_vendor_appears_anywhere_in_the_source():
    """Varrer o src/ inteiro, nao so o registry.

    Um teste que olhasse apenas registry.py deixaria passar o proprio docstring
    que explica que estes nomes nao pertencem ao pacote. A varredura ampla e a
    que vale: se a palavra nao existe no codigo, nao existe o acoplamento.
    """
    leaks = []
    for source in SOURCE.rglob("*.py"):
        text = source.read_text(encoding="utf-8").casefold()
        for vendor in ATS_VENDORS:
            if vendor in text:
                leaks.append(f"{source.name}: {vendor}")
    assert not leaks, f"ATS vendor names leaked into src/: {leaks}"


def test_every_requested_provider_has_a_profile():
    for provider in (
        ChallengeProvider.HCAPTCHA,
        ChallengeProvider.RECAPTCHA,
        ChallengeProvider.RECAPTCHA_ENTERPRISE,
        ChallengeProvider.GENERIC,
    ):
        assert profile_for(provider) is not None


def test_hosts_are_classified_by_profile():
    assert profile_for_host("newassets.hcaptcha.com").provider is ChallengeProvider.HCAPTCHA
    assert profile_for_host("www.google.com").provider in {
        ChallengeProvider.RECAPTCHA,
        ChallengeProvider.RECAPTCHA_ENTERPRISE,
    }
    assert profile_for_host("challenges.cloudflare.com").provider is ChallengeProvider.GENERIC
    assert profile_for_host("example.com") is None
    assert profile_for_host("") is None


def test_every_provider_declares_the_hosts_it_needs_to_run():
    """O guard informa o requisito de rede; ele nao concede acesso."""
    for profile in profiles():
        assert profile.runtime_hosts, f"{profile.provider.value} declares no runtime hosts"


def test_response_markers_map_text_to_a_concept():
    profile = profile_for(ChallengeProvider.RECAPTCHA_ENTERPRISE)
    marker = profile.marker_for("There was an error verifying your application.")
    assert marker is not None
    assert marker.kind is ChallengeSignalKind.VERIFICATION_REJECTED
    assert marker.token == "error_verifying_application"


def test_an_unrelated_text_matches_no_marker():
    for profile in profiles():
        assert profile.marker_for("Your application was received.") is None
        assert profile.marker_for("") is None


def test_the_enterprise_profile_carries_no_dom_markers():
    """Enterprise e invisivel: quem o distingue e a resposta, nao a pagina."""
    assert profile_for(ChallengeProvider.RECAPTCHA_ENTERPRISE).dom_markers == ()


# --- signals ------------------------------------------------------------------


def test_a_signal_names_its_source_and_validates_confidence():
    with pytest.raises(ValueError):
        ChallengeSignal(kind=ChallengeSignalKind.CHALLENGE_VISIBLE, source="")
    with pytest.raises(ValueError):
        ChallengeSignal(kind=ChallengeSignalKind.CHALLENGE_VISIBLE, source="dom", confidence=1.5)


def test_a_signal_detail_must_be_a_short_token_never_provider_text():
    """Um campo livre viraria um lugar para despejar payload na evidencia."""
    ok = ChallengeSignal(
        kind=ChallengeSignalKind.VERIFICATION_REJECTED, source="response", detail="error_verifying_application"
    )
    assert ok.detail
    with pytest.raises(ValueError):
        ChallengeSignal(
            kind=ChallengeSignalKind.VERIFICATION_REJECTED,
            source="response",
            detail="There was an error verifying your application.",
        )
    with pytest.raises(ValueError):
        ChallengeSignal(kind=ChallengeSignalKind.VERIFICATION_REJECTED, source="response", detail="a" * 80)


# --- a policy nao pode conhecer texto de provedor -----------------------------


def test_the_policy_contains_no_provider_phrase():
    """Os textos concretos pertencem ao registry; a policy usa conceitos."""
    source = (SOURCE / "policy.py").read_text(encoding="utf-8").casefold()
    for profile in profiles():
        for marker in profile.response_markers:
            assert marker.phrase not in source, f"policy.py knows the phrase {marker.phrase!r}"
    for leaked in ("recaptcha", "hcaptcha", "turnstile", "cloudflare"):
        assert leaked not in source, f"policy.py knows the vendor {leaked!r}"


def test_the_challenge_guard_never_solves_anything():
    """A fronteira e executavel: nenhuma funcao ou classe com nome proibido."""
    banned = ("solve", "bypass", "stealth", "answer_captcha", "inject_token", "spoof")
    from challenge_guard import __all__ as public_api

    for name in public_api:
        assert not any(token in name.casefold() for token in banned), name
    for source in SOURCE.rglob("*.py"):
        text = source.read_text(encoding="utf-8").casefold()
        for token in banned:
            assert f"def {token}" not in text, f"{source.name} defines {token}"
