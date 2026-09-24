"""CG-012: requisitos de rede do challenge."""

from __future__ import annotations

import pytest

from challenge_guard import (
    ChallengeNetworkPurpose,
    ChallengeNetworkRequirement,
    ChallengeProvider,
    requirements_for,
    source_votes,
    independent_sources,
    corroborated_confidence,
    ChallengeSignal,
    ChallengeSignalKind,
)


def _requirement(**overrides):
    data = {
        "provider": ChallengeProvider.HCAPTCHA,
        "purpose": ChallengeNetworkPurpose.CHALLENGE_RUNTIME,
        "origins": ("hcaptcha.com",),
        "path_patterns": (r"^/getcaptcha/",),
        "max_requests": 10,
    }
    data.update(overrides)
    return ChallengeNetworkRequirement(**data)


def test_a_wildcard_origin_requires_a_known_path():
    """`*.dominio` + caminho aberto autoriza um dominio inteiro — foi o defeito real."""
    with pytest.raises(ValueError, match="requires a known path"):
        _requirement(origins=("*.hcaptcha.com",), path_patterns=())


def test_a_catch_all_path_is_refused_outright():
    for pattern in (r"^/.*$", ".*", "^.*$"):
        with pytest.raises(ValueError, match="catch-all"):
            _requirement(path_patterns=(pattern,))


def test_an_unknown_path_is_stated_by_omission_not_by_a_permissive_default():
    """Ausencia de path significa 'nao sei', e o host precisa decidir."""
    requirement = _requirement(origins=("hcaptcha.com",), path_patterns=())
    assert requirement.paths_known is False
    assert requirement.is_scoped is False


def test_origins_must_be_bare_lowercase_hosts():
    for bad in ("https://hcaptcha.com", "HCAPTCHA.com", "hcaptcha.com/", ""):
        with pytest.raises(ValueError):
            _requirement(origins=(bad,))


def test_methods_must_be_uppercase_and_the_budget_positive():
    with pytest.raises(ValueError):
        _requirement(methods=("get",))
    with pytest.raises(ValueError):
        _requirement(max_requests=0)


def test_permits_origin_is_description_only_and_handles_wildcards():
    requirement = _requirement(origins=("hcaptcha.com", "*.hcaptcha.com"))
    assert requirement.permits_origin("hcaptcha.com") is True
    assert requirement.permits_origin("api.hcaptcha.com") is True
    assert requirement.permits_origin("evil-hcaptcha.com") is False
    assert requirement.permits_origin("example.com") is False


def test_every_scoped_requirement_declares_a_real_path():
    for provider in (
        ChallengeProvider.HCAPTCHA,
        ChallengeProvider.RECAPTCHA,
        ChallengeProvider.RECAPTCHA_ENTERPRISE,
    ):
        for requirement in requirements_for(provider):
            assert requirement.purpose is ChallengeNetworkPurpose.CHALLENGE_RUNTIME
            assert requirement.is_scoped, f"{provider.value} declares an unscoped requirement"
            assert requirement.max_requests >= 1


def test_generic_gets_no_automatic_grant():
    """Generic nao tem requisito declarado: 'nao sei' e nao 'pode tudo'."""
    assert requirements_for(ChallengeProvider.GENERIC) == ()


def test_an_unknown_provider_has_no_requirement():
    assert requirements_for(ChallengeProvider.UNKNOWN) == ()


def test_challenge_runtime_is_a_separate_purpose_from_anything_else():
    """Nao existe proposito de upload nem de submissao nesta biblioteca."""
    purposes = {purpose.value for purpose in ChallengeNetworkPurpose}
    assert purposes == {"challenge_runtime"}
    for forbidden in ("upload", "submission", "inspection"):
        assert forbidden not in purposes


# --- corroboracao por fonte ---------------------------------------------------


def _signal(source: str, confidence: float = 0.8) -> ChallengeSignal:
    return ChallengeSignal(
        kind=ChallengeSignalKind.CHALLENGE_VISIBLE, source=source, confidence=confidence
    )


def test_fifteen_signals_from_one_observer_are_one_vote():
    """O defeito real: dois seletores de DOM casando valiam como duas provas."""
    many_dom = tuple(_signal("dom") for _ in range(15))
    assert independent_sources(many_dom) == ("dom",)
    assert len(source_votes(many_dom)) == 1
    assert corroborated_confidence(many_dom) == pytest.approx(0.8)


def test_three_independent_sources_corroborate():
    signals = (_signal("dom"), _signal("frames"), _signal("network", 0.7))
    assert independent_sources(signals) == ("dom", "frames", "network")
    assert len(source_votes(signals)) == 3
    assert corroborated_confidence(signals) > 0.8


def test_corroboration_cannot_exceed_one():
    signals = tuple(_signal(source, 1.0) for source in ("dom", "frames", "network", "response", "extra"))
    assert corroborated_confidence(signals) == 1.0


def test_no_signals_means_no_confidence():
    assert corroborated_confidence(()) == 0.0
    assert independent_sources(()) == ()
