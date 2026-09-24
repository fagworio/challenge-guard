"""Sinais normalizados com proveniencia.

Observadores veem coisas concretas — um container no DOM, um iframe, um POST
para o runtime do provedor, um texto de resposta. A policy nao pode conhecer
esses detalhes: ela raciocina sobre conceitos.

O sinal e a fronteira entre os dois mundos:

    raw response
        -> ResponseObserver
        -> provider profile   (onde os textos concretos vivem)
        -> ChallengeSignal(kind=VERIFICATION_REJECTED)
        -> policy
        -> PROVIDER_REJECTED

`detail` carrega um TOKEN curto e controlado (o id do marcador que casou),
nunca o texto do provedor: um campo livre viraria, na pratica, um lugar para
despejar payload na evidencia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .models import ChallengeProvider


class ChallengeSignalKind(str, Enum):
    """Conceitos que a policy entende. Conjunto fechado."""

    #: Estrutura de challenge visivel (widget, container, iframe de desafio).
    CHALLENGE_VISIBLE = "challenge_visible"
    #: Trafego de METADADOS para o runtime do provedor.
    CHALLENGE_TRAFFIC = "challenge_traffic"
    #: O provedor pediu explicitamente que um challenge seja completado.
    CHALLENGE_REQUIRED = "challenge_required"
    #: O provedor recusou por nao conseguir verificar a origem do envio.
    VERIFICATION_REJECTED = "verification_rejected"
    #: Avaliacao de risco puramente automatica, sem interacao.
    RISK_ASSESSMENT_ONLY = "risk_assessment_only"


_SAFE_DETAIL = re.compile(r"^[a-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class ChallengeSignal:
    kind: ChallengeSignalKind
    source: str
    provider: ChallengeProvider = ChallengeProvider.UNKNOWN
    confidence: float = 0.0
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("a signal must name its source")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.detail and not _SAFE_DETAIL.match(self.detail):
            raise ValueError(
                "signal detail must be a short controlled token, never provider text"
            )

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind.value, self.source)


def strongest(signals: tuple[ChallengeSignal, ...], kind: ChallengeSignalKind) -> ChallengeSignal | None:
    """O sinal de maior confianca para um conceito, ou None."""
    matching = [signal for signal in signals if signal.kind is kind]
    if not matching:
        return None
    return max(matching, key=lambda signal: signal.confidence)


def has_kind(signals: tuple[ChallengeSignal, ...], *kinds: ChallengeSignalKind) -> bool:
    wanted = set(kinds)
    return any(signal.kind in wanted for signal in signals)
