"""CG-027/CG-031 — Validation Guard.

A regra, em uma linha:

```text
acao terminou  !=  challenge resolvido
```

Ela parece obvia e e violada o tempo todo, porque o sinal de "terminei" costuma
vir do lugar errado: o executor diz que acabou, o browser diz que a pagina
mudou, o host diz que o humano clicou. Nenhum desses e evidencia de que o
desafio saiu do caminho.

A validacao so aceita uma coisa como progresso: uma observacao NOVA, feita
DEPOIS, na qual o guard nao detecta mais o desafio. E ela nunca promove
`unknown` a `resolved` — na duvida o host espera, que e o desfecho barato.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import ChallengeObservation, ReasonToken


@dataclass(frozen=True)
class ValidationResult:
    """Veredito da revalidacao, com o motivo no conjunto fechado."""

    progressed: bool
    resolved: bool
    reason_token: str
    detected_before: bool
    detected_after: bool
    write_seen: bool = False


def validate_progress(
    *,
    previous: ChallengeObservation | None,
    current: ChallengeObservation,
    browser_write_sent: bool = False,
    submission_confirmed: bool = False,
) -> ValidationResult:
    """Compara duas observacoes e diz o que mudou — nunca o que se espera.

    `browser_write_sent` entra na conta apenas para ser DESCARTADO como prova de
    resolucao: uma escrita que saiu nao diz que o desafio foi embora. Ele aparece
    no resultado para a auditoria poder mostrar que existia e nao foi usado.
    """
    before = bool(previous.detected) if previous is not None else False
    after = bool(current.detected)

    if submission_confirmed:
        # A confirmacao do provedor encerra a pergunta do challenge: se a
        # candidatura foi aceita, o desafio nao esta mais no caminho.
        return ValidationResult(
            progressed=True,
            resolved=True,
            reason_token=ReasonToken.SUBMISSION_CONFIRMED_OVERRIDES_CHALLENGE.value,
            detected_before=before,
            detected_after=after,
            write_seen=browser_write_sent,
        )

    if not before:
        # Nao havia desafio: nao ha resolucao a validar.
        return ValidationResult(
            progressed=False,
            resolved=False,
            reason_token=ReasonToken.CHALLENGE_ABSENT.value,
            detected_before=False,
            detected_after=after,
            write_seen=browser_write_sent,
        )

    if after:
        # Ainda presente — inclusive quando a acao "terminou". Este e o caso que
        # o executor costuma errar: `action_finished` nao chega aqui como fato.
        return ValidationResult(
            progressed=False,
            resolved=False,
            reason_token=ReasonToken.CHALLENGE_DETECTED_INTERACTIVE.value
            if current.challenge_type.interactive
            else ReasonToken.CHALLENGE_OBSERVED_NON_INTERACTIVE.value,
            detected_before=True,
            detected_after=True,
            write_seen=browser_write_sent,
        )

    # Detectado antes, ausente agora: progresso REAL, observado.
    return ValidationResult(
        progressed=True,
        resolved=True,
        reason_token=ReasonToken.CHALLENGE_RESOLVED_EXTERNALLY.value,
        detected_before=True,
        detected_after=False,
        write_seen=browser_write_sent,
    )


def validate_not_premature(
    *,
    claimed_resolved: bool,
    current: ChallengeObservation,
    previous: ChallengeObservation | None = None,
) -> None:
    """Recusa a declaracao de resolucao sem observacao nova que a sustente."""
    if not claimed_resolved:
        return
    if current is None:
        raise ValueError("resolution cannot be claimed without a fresh observation")
    if current.detected:
        raise ValueError("resolution cannot be claimed while the challenge is still observed")
    if previous is None or not previous.detected:
        raise ValueError("resolution requires a previous observation in which the challenge WAS observed")


__all__ = ["ValidationResult", "validate_not_premature", "validate_progress"]
