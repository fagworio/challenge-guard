"""Motor de politica: as regras de precedencia (CG-006).

A ordem das regras E a especificacao. Elas sao avaliadas de cima para baixo e a
primeira que casa decide:

1. Confirmacao real vence. Uma submissao comprovada nunca e rebaixada por um
   iframe de CAPTCHA que continua no DOM.
2. Desaparecimento nao e sucesso — e `RESOLVED_EXTERNALLY`. Quem valida o
   resultado e o host.
3. Escrita enviada + evidencia anti-bot = provedor recusou.
4. Desafio interativo sem escrita = precisa de humano.
5. Desafio nao interativo = apenas observar; ele pode liberar sozinho.
6. Ambiguidade = `UNKNOWN`.

StatusCode sozinho nunca classifica CAPTCHA: HTTP 400 sem evidencia adicional
nao e rejeicao anti-bot, e tratar como se fosse produziria falso positivo em
qualquer validacao comum de formulario.
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

#: Abaixo disto, a propria deteccao e duvidosa: nao se pede humano nem se
#: afirma rejeicao com base em sinal fraco.
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

#: Marcadores de que o provedor RECUSOU por anti-bot. Precisam ser texto
#: explicito: a presenca de um widget, sozinha, nao prova recusa.
_REJECTION_MARKERS = (
    "please complete the recaptcha",
    "complete the captcha",
    "captcha verification",
    "verification failed",
    "verification error",
    # Mensagem real observada no Lever/CI&T: "There was an error verifying your
    # application." — "verify" nao casa com "verifying", entao a forma exata do
    # gerundio precisa estar aqui ou o caso real passa batido.
    "verifying your application",
    "error verifying",
    "challenge failed",
    "captcha required",
    "unable to verify",
)


def _has_rejection_evidence(observation: ChallengeObservation) -> bool:
    haystack = " ".join(
        [*observation.response_signals, *observation.network_signals]
    ).casefold()
    return any(marker in haystack for marker in _REJECTION_MARKERS)


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

        rejected = _has_rejection_evidence(observation)

        # 4. Escrita saiu e ha evidencia de recusa: handoff de mile final.
        if observation.browser_write_sent and rejected:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.PROVIDER_REJECTED,
                provider=provider,
                reason_token=ReasonToken.PROVIDER_REJECTED_SUBMISSION.value,
                human_required=True,
                retry_allowed=False,
                confidence=observation.confidence,
            )

        # 5. Escrita saiu mas sem evidencia suficiente: nao se afirma recusa.
        if observation.browser_write_sent and not rejected:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.OBSERVE,
                provider=provider,
                reason_token=ReasonToken.CHALLENGE_AFTER_WRITE_AWAITING_EVIDENCE.value,
                human_required=False,
                retry_allowed=False,
                confidence=observation.confidence,
            )

        # 6. Nada saiu: o desafio esta bloqueando o fluxo.
        if observation.challenge_type.interactive:
            return ChallengeDecision(
                status=ChallengeDecisionStatus.NEEDS_HUMAN,
                provider=provider,
                reason_token=(
                    ReasonToken.CHALLENGE_DETECTED_PRE_SUBMIT.value
                    if observation.phase in PRE_SUBMISSION_PHASES
                    else ReasonToken.CHALLENGE_DETECTED_INTERACTIVE.value
                ),
                human_required=True,
                retry_allowed=True,
                confidence=observation.confidence,
            )

        # 7. Nao interativo: pode liberar sozinho. Observar, nunca pedir humano.
        return ChallengeDecision(
            status=ChallengeDecisionStatus.OBSERVE,
            provider=provider,
            reason_token=ReasonToken.CHALLENGE_OBSERVED_NON_INTERACTIVE.value,
            human_required=False,
            retry_allowed=False,
            confidence=observation.confidence,
        )

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
