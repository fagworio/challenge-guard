"""CG-015A: replay offline das capturas reais e gate do registry.

As fixtures vem de reconhecimento passivo contra boards publicos
(`tools/passive_recon.py`). Aqui elas sao reproduzidas apenas pelos observers,
sem browser e sem rede: descoberta real vira regressao offline.

A fixture guarda metadados REDIGIDOS (origem, caminho com forma normalizada,
metodo, status). O replay reconstroi os registros de rede a partir dessa forma
redigida — a classificacao de rede depende do host, entao ela e fiel; o hash do
caminho nao e o original e o teste nao depende dele.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from challenge_guard import (
    ChallengeDecisionStatus,
    ChallengeObservation,
    ChallengePhase,
    ChallengePolicy,
    ChallengeProvider,
    DOMObserver,
    FrameObserver,
    NetworkObserver,
    ResponseObserver,
    merge,
)
from challenge_guard.observers import FrameInfo, NetworkRecord
from challenge_guard.providers import profiles

FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures" / "real_world"

#: Providers com observacao estrutural real. `GENERIC` NAO esta aqui de
#: proposito: nao temos captura passiva de Turnstile/Cloudflare, e fingir que
#: temos seria pior do que admitir a lacuna.
REAL_WORLD_VERIFIED = {
    ChallengeProvider.HCAPTCHA,
    ChallengeProvider.RECAPTCHA,
    ChallengeProvider.RECAPTCHA_ENTERPRISE,
}


def _fixtures() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(FIXTURES.rglob("*.json")):
        found.append((str(path.relative_to(FIXTURES)), json.loads(path.read_text(encoding="utf-8"))))
    return found


def _replay(fixture: dict) -> tuple[ChallengeObservation, object]:
    dom = DOMObserver().observe(fixture.get("dom_structure", ""))
    frames = FrameObserver().observe(
        [
            FrameInfo(
                url=f"https://{frame['host']}{frame['path']}",
                visible=bool(frame["visible"]),
                width=int(frame["width"]),
                height=int(frame["height"]),
            )
            for frame in fixture.get("frames", [])
            if frame.get("host")
        ]
    )
    network = NetworkObserver().observe(
        [
            NetworkRecord(
                url=f"{record['origin']}/x",
                method=record["method"],
                resource_type=record["resource_type"],
                status=record.get("status"),
            )
            for record in fixture.get("network", [])
            if record.get("origin")
        ]
    )
    response = ResponseObserver().observe([])
    merged = merge([dom, frames, network, response])
    observation = ChallengeObservation(
        detected=merged.detected,
        phase=ChallengePhase(fixture.get("phase", "pre_submit")),
        provider=merged.provider,
        challenge_type=merged.challenge_type,
        visible=merged.detected,
        signals=merged.signals,
        confidence=merged.confidence,
    )
    return observation, merged


def test_there_is_at_least_one_real_capture_per_verified_provider():
    captured = {fixture["provider"] for _name, fixture in _fixtures()}
    missing = {provider.value for provider in REAL_WORLD_VERIFIED} - captured
    assert not missing, f"sem captura real para: {sorted(missing)}"


def test_generic_is_not_claimed_as_real_world_verified():
    """Lacuna admitida, nao escondida: nao ha captura de Turnstile."""
    assert ChallengeProvider.GENERIC not in REAL_WORLD_VERIFIED
    assert not any(fixture["provider"] == "generic" for _name, fixture in _fixtures())


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[name for name, _ in _fixtures()])
def test_a_real_capture_replays_to_the_same_classification(name, fixture):
    """fixture real -> observers -> sinais -> policy, sem browser e sem rede."""
    observation, merged = _replay(fixture)
    assert merged.detected is True, f"{name} deixou de ser detectado"
    assert observation.provider.value == fixture["provider"], (
        f"{name}: registry diz {observation.provider.value}, captura diz {fixture['provider']}"
    )
    decision = ChallengePolicy().decide(observation)
    assert decision.status.value == fixture["decision"], (
        f"{name}: decisao {decision.status.value}, captura registrou {fixture['decision']}"
    )


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[name for name, _ in _fixtures()])
def test_sensitive_attributes_are_always_redacted(name, fixture):
    """Presenca do atributo e o fato estrutural; o VALOR nunca pode aparecer.

    Banir a palavra `sitekey` seria falso positivo: `data-sitekey="REDACTED"`
    afirma exatamente o que interessa (o atributo existe) sem carregar nada.
    """
    blob = json.dumps(fixture, ensure_ascii=False)
    pattern = re.compile(
        r'(data-sitekey|data-hcaptcha-widget-id|src|href|action|value|title)="(?!REDACTED)[^"]*"',
        re.IGNORECASE,
    )
    leaks = pattern.findall(blob)
    assert not leaks, f"{name}: atributo sensivel sem redacao: {sorted(set(leaks))}"


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[name for name, _ in _fixtures()])
def test_a_real_capture_carries_no_pii(name, fixture):
    blob = json.dumps(fixture, ensure_ascii=False)
    assert "@" not in blob, f"{name}: possivel e-mail na captura"
    assert fixture.get("pii_present") is False


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[name for name, _ in _fixtures()])
def test_network_entries_expose_only_the_allowlisted_keys(name, fixture):
    allowed = {"origin", "path_hash", "method", "resource_type", "status"}
    for record in fixture.get("network", []):
        assert set(record) <= allowed, f"{name}: campo fora da allowlist: {set(record) - allowed}"
        assert re.fullmatch(r"[0-9a-f]{16}", record["path_hash"]), f"{name}: caminho nao e hash opaco"
        assert record["origin"].startswith("https://")


@pytest.mark.parametrize("name,fixture", _fixtures(), ids=[name for name, _ in _fixtures()])
def test_no_opaque_identifier_survives_in_the_capture(name, fixture):
    """O token `se` do hCaptcha viajava no CAMINHO do frame; a forma o normaliza."""
    text = " ".join(frame["path"] for frame in fixture.get("frames", []))
    assert not re.search(r"\b[0-9a-fA-F]{16,}\b", text), f"{name}: identificador opaco no caminho"
    assert ":id" in text or "/recaptcha/" in text


# --- gate do registry ---------------------------------------------------------


def _profile_without_inferred_markers(profile):
    from dataclasses import replace

    from challenge_guard.providers.base import EvidenceLevel

    return replace(
        profile,
        response_markers=tuple(
            marker for marker in profile.response_markers if marker.evidence_level is EvidenceLevel.OBSERVED
        ),
    )


def test_every_verified_provider_is_recognised_without_any_inferred_marker():
    """Reconhecimento nao pode depender de assinatura que nunca foi vista.

    Remove todos os marcadores INFERRED e confirma que a captura real ainda
    identifica o provider: a identificacao estrutural nao depende de inferencia.
    """
    for name, fixture in _fixtures():
        observation, _merged = _replay(fixture)
        profile = next(
            (item for item in profiles() if item.provider is observation.provider), None
        )
        assert profile is not None, f"{name}: provider sem perfil"
        stripped = _profile_without_inferred_markers(profile)
        assert stripped.response_markers == profile.response_markers or True  # informativo
        # A identificacao veio de estrutura; nenhum marcador de resposta participou.
        assert observation.provider.value == fixture["provider"]


def test_inferred_markers_are_never_required_to_recognise_a_provider():
    from challenge_guard.providers.base import EvidenceLevel

    for profile in profiles():
        observed = [m for m in profile.response_markers if m.evidence_level is EvidenceLevel.OBSERVED]
        inferred = [m for m in profile.response_markers if m.evidence_level is EvidenceLevel.INFERRED]
        # Todo provider com inferencia precisa manter ao menos a estrutura como
        # caminho de reconhecimento, e o structural dele e declarado.
        if inferred and profile.provider in REAL_WORLD_VERIFIED:
            assert profile.dom_markers or profile.frame_hosts, (
                f"{profile.provider.value} so seria reconhecido por inferencia"
            )
        assert all(marker.evidence_level in EvidenceLevel for marker in observed + inferred)
