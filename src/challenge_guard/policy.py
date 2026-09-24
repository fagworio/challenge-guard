"""Motor de politica: as regras de precedencia (CG-006).

A policy raciocina sobre CONCEITOS, nunca sobre textos de provedor. Ela recebe
sinais ja normalizados (ver signals.py); os textos concretos vivem nos perfis
declarativos do registry. Um teste garante que nenhuma frase de provedor
reapareca neste arquivo.

A ordem das regras E a especificacao:

1. Confirmacao real vence. Submissao comprovada nunca e rebaixada por um iframe
   de CAPTCHA que continua no DOM.
2. Desaparecimento nao e sucesso — e `RESOLVED_EXTERNALLY`.
3. Deteccao fraca nao autoriza decisao forte.
4. Escrita entregue + evidencia de recusa = provedor recusou.
5. Escrita entregue sem evidencia decisiva = observar. Widget sozinho nao prova
   recusa.
6. O provedor PEDIU o challenge e nada saiu = precisa de humano, mesmo que o
   tipo observado seja invisivel.
7. Desafio interativo sem escrita = precisa de humano.
8. Nao interativo e sem exigencia do provedor = observar.

As regras 6 e 8 juntas evitam os dois erros opostos: pedir humano cedo demais
por causa de um selo invisivel em PAGE_LOAD, e deixar passar um 400/428 real em
que o provedor recusou uma submissao entregue.

StatusCode sozinho nunca classifica CAPTCHA: sem sinal de recusa, um HTTP 400
e validacao comum de formulario.
"""

from __future__ import annotations

from .models import (
    ChallengeDecision,
    ChallengeDecisionStatus,
    ChallengeObservation,
    ChallengePhase,
    ChallengeProvider,
    ChallengeSession,
    ChallengeSessionStatus,
    ChallengeType,
    ReasonToken,
)
from .signals import ChallengeSignalKind, has_kind, strongest

#: Abaixo disto, a propria deteccao e duvidosa.
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

#: Fases que acontecem antes de qualquer escrita de submissao sair.
PRE_SUBMISSION_PHASES = frozenset(
    {
        ChallengePhase.PAGE_LOAD,
        ChallengePhase.FORM_DISCOVERY,
        ChallengePhase.FORM_FILL,
        ChallengePhase.PRE_SUBMIT,
    }
)

#: Conceitos que, somados a uma escrita entregue, configuram recusa do provedor.
_REJECTION_KINDS = (
    ChallengeSignalKind.VERIFICATION_REJECTED,
    ChallengeSignalKind.CHALLENGE_REQUIRED,
)


class ChallengePolicy:
    """Traduz observacao + sessao em uma decisao de dominio."""

    def __init__(self, *, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self.confidence_threshold = confidence_threshold

    def decide(
        self,
        observation: ChallengeObservation,
        session: ChallengeSession | None = None,
        *,
        submission_confirmed: bool = False,
    ) -> ChallengeDecision:
        provider = observation.provider
        if session is not None and provider is ChallengeProvider.UNKNOWN:
            provider = session.provider

        # 1. Confirmacao real vence tudo.
        if submission_confirmed:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.NONE,
                provider=provider,
                reason_token=ReasonToken.SUBMISSION_CONFIRMED_OVERRIDES_CHALLENGE.value,
                human_required=False,
                retry_allowed=False,
                confidence=1.0,
            )

        # 2. Nada detectado agora.
        if not observation.detected:
            if self._disappeared(session):
                return ChallengeDecision(
                    status=ChallengeDecisionStatus.RESOLVED_EXTERNALLY,
                    provider=provider,
                    reason_token=ReasonToken.CHALLENGE_RESOLVED_EXTERNALLY.value,
                    human_required=False,
                    retry_allowed=False,
                    confidence=observation.confidence,
                )
            return ChallengeDecision(
                status=ChallengeDecisionStatus.NONE,
                provider=provider,
                reason_token=ReasonToken.CHALLENGE_ABSENT.value,
                confidence=observation.confidence,
            )

        # 3. Deteccao fraca nao autoriza decisao forte.
        if observation.confidence < self.confidence_threshold:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.UNKNOWN,
                provider=provider,
                reason_token=ReasonToken.CHALLENGE_AMBIGUOUS.value,
                confidence=observation.confidence,
            )

        # O provedor pediu o challenge explicitamente? E o unico sinal que
        # autoriza tratar um tipo nao interativo como bloqueio.
        demanded = strongest(observation.signals, ChallengeSignalKind.CHALLENGE_REQUIRED) is not None
        rejected = has_kind(observation.signals, *_REJECTION_KINDS)

        # 4. Escrita entregue + evidencia de recusa: mile final humano.
        if observation.browser_write_sent and rejected:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.PROVIDER_REJECTED,
                provider=provider,
                reason_token=ReasonToken.PROVIDER_REJECTED_SUBMISSION.value,
                human_required=True,
                retry_allowed=False,
                confidence=observation.confidence,
            )

        # 5. Escrita entregue sem evidencia suficiente: nao se afirma recusa.
        if observation.browser_write_sent:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.OBSERVE,
                provider=provider,
                reason_token=ReasonToken.CHALLENGE_AFTER_WRITE_AWAITING_EVIDENCE.value,
                human_required=False,
                retry_allowed=False,
                confidence=observation.confidence,
            )

        # 6. O provedor exigiu o challenge e nada saiu: bloqueio real, mesmo que
        #    o tipo observado seja invisivel.
        if demanded:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.NEEDS_HUMAN,
                provider=provider,
                reason_token=self._observed_token(observation),
                human_required=True,
                retry_allowed=True,
                confidence=observation.confidence,
            )

        # 7. Desafio interativo sem escrita: precisa de humano.
        if observation.challenge_type.interactive:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.NEEDS_HUMAN,
                provider=provider,
                reason_token=self._observed_token(observation),
                human_required=True,
                retry_allowed=True,
                confidence=observation.confidence,
            )

        # 8. Nao interativo e sem exigencia do provedor: observar.
        return ChallengeDecision(
            status=ChallengeDecisionStatus.OBSERVE,
            provider=provider,
            reason_token=ReasonToken.CHALLENGE_OBSERVED_NON_INTERACTIVE.value,
            human_required=False,
            retry_allowed=False,
            confidence=observation.confidence,
        )

    def timed_out(
        self,
        provider: ChallengeProvider = ChallengeProvider.UNKNOWN,
        *,
        confidence: float = 0.0,
    ) -> ChallengeDecision:
        """A espera por um humano acabou sem desfecho.

        Nao e `PROVIDER_REJECTED`: nada foi recusado — apenas nao terminou a
        tempo. Continua precisando de humano, e o host decide se reoferece o
        handoff.
        """
        return ChallengeDecision(
            status=ChallengeDecisionStatus.UNKNOWN,
            provider=provider,
            reason_token=ReasonToken.HUMAN_OBSERVATION_TIMEOUT.value,
            human_required=True,
            retry_allowed=True,
            confidence=confidence,
        )

    @staticmethod
    def _observed_token(observation: ChallengeObservation) -> str:
        if observation.phase in PRE_SUBMISSION_PHASES:
            return ReasonToken.CHALLENGE_DETECTED_PRE_SUBMIT.value
        return ReasonToken.CHALLENGE_DETECTED_INTERACTIVE.value

    @staticmethod
    def _disappeared(session: ChallengeSession | None) -> bool:
        if session is None:
            return False
        return session.status in {
            ChallengeSessionStatus.DISAPPEARED,
            ChallengeSessionStatus.COMPLETED,
        }


def is_interactive(challenge_type: ChallengeType) -> bool:
    return challenge_type.interactive
