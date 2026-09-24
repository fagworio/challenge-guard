"""Ponto de entrada do host (CG-019).

Compoe observadores, sessao e policy. Sem browser, o nucleo continua puro: o
adapter do Playwright so e importado quando um browser e de fato fornecido, para
que `import challenge_guard` nunca puxe uma dependencia opcional.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from .handoff import HumanHandoff, build_handoff
from .models import (
    ChallengeDecision,
    ChallengeDecisionStatus,
    ChallengeObservation,
    ChallengePhase,
    ChallengeProvider,
    ChallengeSession,
    ChallengeType,
)
from .observers import (
    DOMObserver,
    FrameObserver,
    NetworkObserver,
    ObserverResult,
    ResponseObserver,
    ResponseRecord,
    merge,
)
from .policy import ChallengePolicy
from .session import ChallengeSessionTracker


class ChallengeMonitor:
    """Observa uma pagina e responde: precisa de humano, e o que a pessoa faz?"""

    def __init__(
        self,
        browser: Any | None = None,
        *,
        confidence_threshold: float = 0.5,
    ) -> None:
        self._tracker = ChallengeSessionTracker()
        self._policy = ChallengePolicy(confidence_threshold=confidence_threshold)
        self._adapter: Any | None = None
        self._session: ChallengeSession | None = None
        self._last_observation: ChallengeObservation | None = None
        self._last_decision: ChallengeDecision | None = None
        if browser is not None:
            self.attach(browser)

    # -- browser (opcional) ----------------------------------------------------

    def attach(self, browser: Any) -> None:
        """Liga o monitor a um browser. Importa o adapter so aqui."""
        if self._adapter is None:
            from .browser.playwright import PlaywrightChallengeAdapter

            self._adapter = PlaywrightChallengeAdapter()
        self._adapter.attach(browser)

    def detach(self) -> None:
        if self._adapter is not None:
            self._adapter.detach()

    @property
    def attached(self) -> bool:
        return self._adapter is not None and self._adapter.attached

    # -- observacao ------------------------------------------------------------

    def _collect(self) -> list[ObserverResult]:
        if not self.attached:
            return []
        return [
            DOMObserver().observe(self._adapter.collect_dom()),
            FrameObserver().observe(self._adapter.collect_frames()),
            NetworkObserver().observe(self._adapter.collect_network()),
            ResponseObserver().observe(self._adapter.collect_responses()),
        ]

    def observe(
        self,
        *,
        phase: ChallengePhase = ChallengePhase.PRE_SUBMIT,
        http_status: int | None = None,
        response_texts: Iterable[str] = (),
        dom_html: str | None = None,
        browser_write_sent: bool = False,
        submission_confirmed: bool = False,
    ) -> ChallengeObservation:
        """Registra uma rodada e devolve o retrato factual.

        `response_texts` e `dom_html` existem para hosts que ja tem o material em
        maos (uma mensagem de erro colhida do DOM, por exemplo) sem precisar de
        browser anexado.
        """
        results = self._collect()
        if dom_html is not None:
            results.append(DOMObserver().observe(dom_html))
        if response_texts:
            results.append(
                ResponseObserver().observe(
                    [ResponseRecord(status=http_status, text=str(text)) for text in response_texts]
                )
            )
        merged = merge(results)
        observation = ChallengeObservation(
            detected=merged.detected,
            phase=phase,
            provider=merged.provider,
            challenge_type=merged.challenge_type,
            session_id=self._session.id if self._session is not None else "",
            visible=merged.detected,
            browser_write_sent=browser_write_sent,
            http_status=http_status if isinstance(http_status, int) else None,
            dom_signals=merged.structure,
            signals=merged.signals,
            confidence=merged.confidence,
        )
        # A sessao e criada/atualizada DEPOIS de montar a observacao, entao o
        # `session_id` precisa ser reaplicado: sem isso a primeira rodada sai com
        # id vazio e o handoff perde a referencia da sessao.
        if merged.detected and self._session is None:
            self._session = self._tracker.start(observation)
        elif self._session is not None:
            self._tracker.observe(self._session, observation)
        if self._session is not None:
            observation = replace(observation, session_id=self._session.id)
        self._last_observation = observation
        return observation

    def decide(
        self,
        observation: ChallengeObservation | None = None,
        *,
        submission_confirmed: bool = False,
    ) -> ChallengeDecision:
        observation = observation or self._last_observation
        if observation is None:
            raise ValueError("decide requires an observation")
        decision = self._policy.decide(
            observation, self._session, submission_confirmed=submission_confirmed
        )
        self._last_decision = decision
        return decision

    # -- estado ----------------------------------------------------------------

    @property
    def session(self) -> ChallengeSession | None:
        return self._session

    @property
    def observation(self) -> ChallengeObservation | None:
        return self._last_observation

    @property
    def decision(self) -> ChallengeDecision | None:
        return self._last_decision

    @property
    def human_required(self) -> bool:
        return bool(self._last_decision and self._last_decision.human_required)

    def reset(self) -> None:
        """Nova tentativa nao herda sessao nem observacao transitoria."""
        if self._adapter is not None:
            self._adapter.reset()
        self._session = None
        self._last_observation = None
        self._last_decision = None

    def handoff(self, page_url: str = "") -> HumanHandoff | None:
        """O que a pessoa precisa fazer, ou None quando ninguem e necessario."""
        if self._last_decision is None:
            return None
        return build_handoff(
            self._last_decision,
            session_id=self._session.id if self._session is not None else "",
            page_url=page_url,
        )

    def timed_out(self) -> ChallengeDecision:
        """A espera por um humano terminou sem desfecho. Nunca e rejeicao."""
        provider = self._session.provider if self._session is not None else ChallengeProvider.UNKNOWN
        decision = self._policy.timed_out(provider)
        self._last_decision = decision
        return decision


def supported_providers() -> tuple[ChallengeProvider, ...]:
    """Providers com perfil declarado."""
    from .providers.registry import PROFILES

    return tuple(profile.provider for profile in PROFILES)


def challenge_type_of(provider: ChallengeProvider) -> ChallengeType:
    from .providers.registry import profile_for

    profile = profile_for(provider)
    return profile.default_type if profile else ChallengeType.UNKNOWN


__all__ = ["ChallengeMonitor", "ChallengeDecisionStatus", "supported_providers", "challenge_type_of"]
