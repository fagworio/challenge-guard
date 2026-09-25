"""CG-039 — o timeout sabe QUEM estava sendo esperado.

A contradicao que este teste fecha: o guard dizia "espere, o provedor resolve
sozinho" durante os rounds e "precisa de humano" exatamente quando o orcamento
terminava. Se a ACL sozinha fosse mudada, o host continuaria recebendo
`human_required=true` no fim de uma espera autonoma.
"""

from __future__ import annotations

import pytest

from challenge_guard import (
    ChallengeDecisionStatus,
    ChallengeMonitor,
    ChallengeObservation,
    ChallengePhase,
    ChallengePolicy,
    ChallengeProvider,
    ChallengeType,
)
from challenge_guard.guards.provenance import JOURNAL_KINDS  # noqa: F401  (contrato do journal)
from challenge_guard.observers import FrameInfo, NetworkRecord, ResponseRecord
from challenge_guard.resolution.limits import RuntimeLimits
from challenge_guard.runtime import ChallengeRuntime

HTML_CHECKBOX = '<html><body><div class="h-captcha grid-4x4" data-sitekey="x"></div></body></html>'
#: O unico caminho local para `PROVIDER_SUPPORTED` e o frame do Enterprise: o
#: perfil dele nao tem marcador de DOM (`dom_markers=()`), so `frame_paths`.
#: Isso e um FATO medido, e e a razao de a certificacao ponta a ponta de
#: `PROVIDER_SUPPORTED` exigir ambiente autorizado real.
ENTERPRISE_FRAME = "https://www.google.com/recaptcha/enterprise/anchor?k=fixture"


class FakeAdapter:
    """Adapter sem browser: o unico jeito de chegar a INVISIBLE localmente."""

    name = "fixture-adapter"

    def __init__(self, *, frames: list[FrameInfo] | None = None, dom: str = "") -> None:
        self._frames = frames or []
        self._dom = dom
        self.attached = False

    def attach(self, page: object) -> None:
        self.attached = True

    def detach(self) -> None:
        self.attached = False

    def current_url(self) -> str:
        return "https://example.test/apply"

    def collect_dom(self) -> str:
        return self._dom

    def collect_frames(self) -> list[FrameInfo]:
        return list(self._frames)

    def collect_network(self) -> list[NetworkRecord]:
        return []

    def collect_responses(self) -> list[ResponseRecord]:
        return []


def _observation(challenge_type: ChallengeType) -> ChallengeObservation:
    return ChallengeObservation(
        detected=True,
        phase=ChallengePhase.PRE_SUBMIT,
        provider=ChallengeProvider.RECAPTCHA_ENTERPRISE
        if challenge_type is ChallengeType.INVISIBLE
        else ChallengeProvider.HCAPTCHA,
        challenge_type=challenge_type,
        visible=True,
        confidence=0.8,
    )


@pytest.mark.parametrize(
    "human_required,token,expected",
    [
        (True, "human_observation_timeout", True),
        (False, "provider_observation_timeout", False),
    ],
)
def test_the_policy_names_who_was_waited_for(human_required: bool, token: str, expected: bool):
    decision = ChallengePolicy().timed_out(ChallengeProvider.HCAPTCHA, human_required=human_required)
    assert decision.reason_token == token
    assert decision.human_required is expected
    assert decision.status is ChallengeDecisionStatus.UNKNOWN, "expirar nunca e rejeicao"


class StubMonitor:
    """Monitor com observacao cravada: isola o contrato do timeout.

    Nao existe caminho local para DETECTAR um challenge INVISIVEL: o unico
    perfil com esse tipo e o reCAPTCHA Enterprise, que nao tem marcador de DOM
    (`dom_markers=()`), so `frame_paths` de hosts de terceiro. E por isso que a
    certificacao ponta a ponta de `PROVIDER_SUPPORTED` exige ambiente autorizado
    real — o que se testa aqui e o CONTRATO (politica, capability, runtime), nao
    a deteccao.
    """

    def __init__(self, challenge_type: ChallengeType) -> None:
        self.observation = _observation(challenge_type)
        self.decision = None
        self.session = None

    def observe(self, **kwargs: object):
        return self.observation

    def decide(self, observation=None, **kwargs: object):
        self.decision = ChallengePolicy().decide(observation or self.observation, None)
        return self.decision

    def timed_out(self):
        self.decision = ChallengePolicy().timed_out(
            self.observation.provider,
            human_required=self.observation.challenge_type is ChallengeType.CHECKBOX,
        )
        return self.decision

    def reset(self) -> None:
        pass

    def detach(self) -> None:
        pass

    def attach(self, page: object) -> None:
        pass

    def attach_adapter(self, adapter: object, page: object) -> None:
        pass

    def handoff(self, page_url: str = "") -> None:
        return None


def test_a_provider_supported_challenge_does_not_become_human_by_timeout():
    runtime = ChallengeRuntime(
        monitor=StubMonitor(ChallengeType.INVISIBLE),
        limits=RuntimeLimits(max_rounds=1, timeout_seconds=30, max_duration_seconds=60),
    )
    runtime.start()
    try:
        runtime.evaluate()
        decision = runtime.timed_out()
        result = runtime.result()
    finally:
        runtime.close()

    assert decision.human_required is False
    assert decision.reason_token == "provider_observation_timeout"
    assert result.final_status == "expired"
    assert result.human_required is False
    assert result.capability == "provider_supported"


def test_an_interactive_challenge_keeps_needing_a_human_on_timeout():
    monitor = ChallengeMonitor()
    monitor.observe(dom_html=HTML_CHECKBOX, phase=ChallengePhase.PRE_SUBMIT)
    decision = monitor.timed_out()
    assert decision.human_required is True
    assert decision.reason_token == "human_observation_timeout"


def test_the_runtime_reports_expiry_for_a_provider_wait_without_calling_a_human():
    """O caminho que a ACL vai consumir: expira, mas nao pede pessoa."""
    runtime = ChallengeRuntime(
        monitor=StubMonitor(ChallengeType.INVISIBLE),
        limits=RuntimeLimits(max_rounds=1, timeout_seconds=30, max_duration_seconds=60),
    )
    runtime.start()
    try:
        runtime.evaluate()
        runtime.timed_out()
        result = runtime.result()
    finally:
        runtime.close()
    assert result.final_status == "expired"
    assert result.human_required is False
    assert result.capability == "provider_supported"
    assert result.reason_token == "provider_observation_timeout"


def test_the_runtime_expires_by_flag_not_by_reading_the_reason_text():
    """A flag e o fato; o texto do motivo e vocabulario, e pode mudar."""
    runtime = ChallengeRuntime(limits=RuntimeLimits(max_rounds=1, timeout_seconds=30, max_duration_seconds=60))
    runtime.start()
    try:
        runtime.evaluate(dom_html=HTML_CHECKBOX)
        runtime.timed_out()
        assert runtime.result().final_status == "expired"
    finally:
        runtime.close()


def test_the_runtime_result_is_not_expired_before_any_timeout():
    runtime = ChallengeRuntime()
    runtime.start()
    try:
        runtime.evaluate(dom_html=HTML_CHECKBOX)
        assert runtime.result().final_status == "human_required"
    finally:
        runtime.close()
