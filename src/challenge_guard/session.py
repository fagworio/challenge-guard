"""Ciclo de vida da sessao de desafio (CG-003) e sua maquina de estados (CG-004).

Um desafio nao e um booleano: ele aparece, muda de rodada, espera um humano,
desaparece — ou o provedor rejeita a submissao. Este modulo mantem esse
historico. Transicoes invalidas falham alto, porque uma transicao silenciosa
esconderia exatamente o bug que a sessao existe para evitar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Iterable

from .fingerprint import structural_fingerprint
from .models import (
    ChallengeObservation,
    ChallengePhase,
    ChallengeProvider,
    ChallengeRoundObservation,
    ChallengeSession,
    ChallengeSessionStatus,
    ChallengeType,
)


class InvalidChallengeTransition(ValueError):
    """Transicao nao permitida pela maquina de estados."""


class SessionNotFound(KeyError):
    """Sessao desconhecida para o tracker."""


#: Transicoes permitidas. `DETECTED` e o unico ponto de entrada; `COMPLETED` e
#: terminal. `DISAPPEARED` aceita voltar a `ACTIVE` porque um desafio pode
#: reaparecer numa rodada seguinte — negar isso perderia o evento.
TRANSITIONS: dict[ChallengeSessionStatus, frozenset[ChallengeSessionStatus]] = {
    ChallengeSessionStatus.DETECTED: frozenset(
        {
            ChallengeSessionStatus.ACTIVE,
            ChallengeSessionStatus.DISAPPEARED,
            ChallengeSessionStatus.UNKNOWN,
            ChallengeSessionStatus.PROVIDER_REJECTED,
        }
    ),
    ChallengeSessionStatus.ACTIVE: frozenset(
        {
            ChallengeSessionStatus.ROUND_CHANGED,
            ChallengeSessionStatus.WAITING_FOR_HUMAN,
            ChallengeSessionStatus.DISAPPEARED,
            ChallengeSessionStatus.PROVIDER_REJECTED,
            ChallengeSessionStatus.UNKNOWN,
        }
    ),
    ChallengeSessionStatus.ROUND_CHANGED: frozenset(
        {
            ChallengeSessionStatus.ACTIVE,
            ChallengeSessionStatus.WAITING_FOR_HUMAN,
            ChallengeSessionStatus.DISAPPEARED,
            ChallengeSessionStatus.PROVIDER_REJECTED,
            ChallengeSessionStatus.UNKNOWN,
        }
    ),
    ChallengeSessionStatus.WAITING_FOR_HUMAN: frozenset(
        {
            ChallengeSessionStatus.ACTIVE,
            ChallengeSessionStatus.ROUND_CHANGED,
            ChallengeSessionStatus.DISAPPEARED,
            ChallengeSessionStatus.PROVIDER_REJECTED,
            ChallengeSessionStatus.UNKNOWN,
        }
    ),
    ChallengeSessionStatus.DISAPPEARED: frozenset(
        {ChallengeSessionStatus.ACTIVE, ChallengeSessionStatus.COMPLETED}
    ),
    ChallengeSessionStatus.PROVIDER_REJECTED: frozenset({ChallengeSessionStatus.COMPLETED}),
    ChallengeSessionStatus.UNKNOWN: frozenset(
        {
            ChallengeSessionStatus.ACTIVE,
            ChallengeSessionStatus.DISAPPEARED,
            ChallengeSessionStatus.COMPLETED,
        }
    ),
    ChallengeSessionStatus.COMPLETED: frozenset(),
}


def can_transition(current: ChallengeSessionStatus, target: ChallengeSessionStatus) -> bool:
    return target in TRANSITIONS[current]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChallengeSessionTracker:
    """Cria sessoes, acumula rodadas e move o estado."""

    def __init__(self, *, id_factory: Callable[[], str] | None = None) -> None:
        self._sessions: dict[str, ChallengeSession] = {}
        self._counter = 0
        self._id_factory = id_factory

    # -- leitura ---------------------------------------------------------------

    def get(self, session_id: str) -> ChallengeSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    def sessions(self) -> list[ChallengeSession]:
        return list(self._sessions.values())

    def active_sessions(self) -> list[ChallengeSession]:
        return [session for session in self._sessions.values() if session.active]

    # -- escrita ---------------------------------------------------------------

    def _next_id(self) -> str:
        if self._id_factory is not None:
            return str(self._id_factory())
        self._counter += 1
        return f"challenge-session-{self._counter:04d}"

    def transition(
        self, session: ChallengeSession, target: ChallengeSessionStatus
    ) -> ChallengeSession:
        if not can_transition(session.status, target):
            raise InvalidChallengeTransition(
                f"{session.id}: {session.status.value} -> {target.value} is not allowed"
            )
        session.status = target
        if target is ChallengeSessionStatus.DISAPPEARED:
            session.visible = False
        session.last_seen_at = _now()
        return session

    def start(self, observation: ChallengeObservation, *, observed_at: str | None = None) -> ChallengeSession:
        """Abre uma sessao a partir de uma observacao que detectou o desafio."""
        if not observation.detected:
            raise ValueError("cannot start a challenge session from an undetected observation")
        stamp = observed_at or _now()
        session = ChallengeSession(
            id=observation.session_id or self._next_id(),
            provider=observation.provider,
            challenge_type=observation.challenge_type,
            phase=observation.phase,
            first_seen_at=stamp,
            last_seen_at=stamp,
            visible=observation.visible,
        )
        self._sessions[session.id] = session
        self._record_round(session, observation, content_changed=True, observed_at=stamp)
        self.transition(session, ChallengeSessionStatus.ACTIVE)
        return session

    def observe(
        self,
        session: ChallengeSession,
        observation: ChallengeObservation,
        *,
        observed_at: str | None = None,
    ) -> ChallengeSession:
        """Registra uma observacao dentro de uma sessao existente.

        Desaparecimento NAO e sucesso: vira `DISAPPEARED`, e quem decide se o
        fluxo pode continuar e o host.
        """
        stamp = observed_at or _now()
        if session.status is ChallengeSessionStatus.COMPLETED:
            raise InvalidChallengeTransition(f"{session.id}: session is completed")
        if not observation.detected:
            if session.status is not ChallengeSessionStatus.DISAPPEARED:
                self.transition(session, ChallengeSessionStatus.DISAPPEARED)
            return session

        fingerprint = structural_fingerprint(observation)
        changed = bool(session.structure_hash) and fingerprint != session.structure_hash
        session.visible = observation.visible
        session.last_seen_at = stamp
        self._record_round(session, observation, content_changed=changed, observed_at=stamp)
        if changed:
            session.dynamic_content = True
            if session.status is ChallengeSessionStatus.PROVIDER_REJECTED:
                # O provedor ja recusou: nao ha nova rodada a acompanhar, mas o
                # fato observado continua registrado para a auditoria.
                return session
            if can_transition(session.status, ChallengeSessionStatus.ACTIVE):
                self.transition(session, ChallengeSessionStatus.ACTIVE)
            self.transition(session, ChallengeSessionStatus.ROUND_CHANGED)
        elif session.status is ChallengeSessionStatus.ROUND_CHANGED:
            self.transition(session, ChallengeSessionStatus.ACTIVE)
        return session

    def await_human(self, session: ChallengeSession) -> ChallengeSession:
        if session.status is ChallengeSessionStatus.WAITING_FOR_HUMAN:
            return session
        return self.transition(session, ChallengeSessionStatus.WAITING_FOR_HUMAN)

    def provider_rejected(self, session: ChallengeSession) -> ChallengeSession:
        if session.status is ChallengeSessionStatus.PROVIDER_REJECTED:
            return session
        if not can_transition(session.status, ChallengeSessionStatus.PROVIDER_REJECTED):
            return self.transition(session, ChallengeSessionStatus.UNKNOWN)
        return self.transition(session, ChallengeSessionStatus.PROVIDER_REJECTED)

    def complete(self, session: ChallengeSession) -> ChallengeSession:
        if session.status is ChallengeSessionStatus.COMPLETED:
            return session
        if not can_transition(session.status, ChallengeSessionStatus.COMPLETED):
            self.transition(session, ChallengeSessionStatus.DISAPPEARED)
        return self.transition(session, ChallengeSessionStatus.COMPLETED)

    # -- interno ---------------------------------------------------------------

    @staticmethod
    def _refine_knowledge(session: ChallengeSession, observation: ChallengeObservation) -> None:
        if observation.provider is ChallengeProvider.UNKNOWN:
            return
        known = session.provider is not ChallengeProvider.UNKNOWN
        if known and observation.provider is not session.provider:
            if observation.confidence <= session.provider_confidence:
                return
        session.provider = observation.provider
        session.provider_confidence = observation.confidence
        if observation.challenge_type is not ChallengeType.UNKNOWN:
            session.challenge_type = observation.challenge_type

    def _record_round(
        self,
        session: ChallengeSession,
        observation: ChallengeObservation,
        *,
        content_changed: bool,
        observed_at: str,
    ) -> ChallengeRoundObservation:
        fingerprint = structural_fingerprint(observation)
        session.rounds_observed += 1
        session.structure_hash = fingerprint
        # Conhecimento e monotonico salvo evidencia mais forte: uma rodada cega
        # (UNKNOWN) nunca apaga o que ja sabiamos, e trocar por um provider
        # diferente exige confianca MAIOR do que a que estabeleceu o atual.
        self._refine_knowledge(session, observation)
        session.phase = observation.phase
        round_observation = ChallengeRoundObservation(
            session_id=session.id,
            round_number=session.rounds_observed,
            observed_at=observed_at,
            visible=observation.visible,
            content_changed=content_changed,
            structure_hash=fingerprint,
            confidence=observation.confidence,
            evidence_sources=observation.evidence_sources,
        )
        session.rounds.append(round_observation)
        return round_observation


def observed_sessions_for(sessions: Iterable[ChallengeSession], phase: ChallengePhase) -> list[ChallengeSession]:
    """Sessoes cuja ultima rodada ocorreu numa fase do fluxo."""
    return [session for session in sessions if session.phase is phase]


def provider_of(sessions: Iterable[ChallengeSession]) -> ChallengeProvider:
    """Provider dominante entre sessoes, ou UNKNOWN."""
    counts: dict[ChallengeProvider, int] = {}
    for session in sessions:
        counts[session.provider] = counts.get(session.provider, 0) + 1
    if not counts:
        return ChallengeProvider.UNKNOWN
    return max(counts.items(), key=lambda item: item[1])[0]


def latest_type(sessions: Iterable[ChallengeSession]) -> ChallengeType:
    latest = None
    for session in sessions:
        if latest is None or session.last_seen_at > latest.last_seen_at:
            latest = session
    return latest.challenge_type if latest else ChallengeType.UNKNOWN
